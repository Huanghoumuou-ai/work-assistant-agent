from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from json import JSONDecodeError
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import (
    Document,
    DocumentEmbeddingResult,
    DocumentPipelineJob,
    DocumentPipelineJobEvent,
    Project,
)
from backend.app.db.session import SessionLocal
from backend.app.schemas.document import (
    PipelineBatchActionOut,
    PipelineBatchOut,
    PipelineJobEventOut,
    PipelineJobEventsOut,
    PipelineJobListOut,
    PipelineJobOut,
    PipelineStatusOut,
    ProviderCheckOut,
    ProvidersStatusOut,
)
from backend.app.services.chunk_service import chunk_document
from backend.app.services.index_service import index_document
from backend.app.services.parse_service import parse_document


logger = logging.getLogger(__name__)

PIPELINE_STEPS = ["parse", "chunk", "index"]
ACTIVE_STATUSES = {"queued", "running"}
TERMINAL_STATUSES = {"succeeded", "failed", "canceled"}
VALID_STATUSES = ACTIVE_STATUSES | TERMINAL_STATUSES
STEP_START_PROGRESS = {"parse": 10, "chunk": 35, "index": 65}
STEP_DONE_PROGRESS = {"parse": 35, "chunk": 65, "index": 100}
RECOVERED_MESSAGE = "Pipeline job recovered after worker lease expired."


def _api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "success": False,
            "code": code,
            "message": message,
            "data": None,
        },
    )


def _bad_request(message: str) -> HTTPException:
    return _api_error(status.HTTP_400_BAD_REQUEST, "BAD_REQUEST", message)


def _not_found(message: str) -> HTTPException:
    return _api_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", message)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _lock_expires_at(now: datetime | None = None) -> datetime:
    return (now or _utc_now()) + timedelta(seconds=max(60, settings.pipeline_lock_timeout_seconds))


def _worker_concurrency() -> int:
    # Phase 18 intentionally supports one local worker. Keep the config visible
    # while preventing accidental parallel large-file processing.
    return 1 if settings.pipeline_worker_concurrency < 1 else min(settings.pipeline_worker_concurrency, 1)


def _short_error(error: Exception) -> str:
    if isinstance(error, HTTPException):
        detail = error.detail
        if isinstance(detail, dict) and isinstance(detail.get("message"), str):
            return detail["message"][:500]
    message = str(error).strip()
    return message[:500] if message else "Document pipeline failed."


def _error_code(error: Exception) -> str:
    if isinstance(error, HTTPException):
        detail = error.detail
        if isinstance(detail, dict) and isinstance(detail.get("code"), str):
            return detail["code"][:80]
    return error.__class__.__name__[:80]


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _json_dict(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _record_event(
    db: Session,
    job: DocumentPipelineJob,
    event_type: str,
    *,
    step: str | None = None,
    message: str | None = None,
    payload: dict | None = None,
) -> None:
    db.add(
        DocumentPipelineJobEvent(
            job_id=job.id,
            document_id=job.document_id,
            event_type=event_type,
            step=step,
            message=message[:500] if message else None,
            payload_json=json.dumps(payload or {}, ensure_ascii=False),
            created_at=_utc_now(),
        )
    )


def pipeline_job_payload(job: DocumentPipelineJob) -> PipelineJobOut:
    return PipelineJobOut(
        id=job.id,
        document_id=job.document_id,
        status=job.status,
        current_step=job.current_step,
        steps=_json_list(job.steps_json),
        step_results=_json_dict(job.step_results_json),
        cancel_requested=bool(job.cancel_requested),
        progress_percent=job.progress_percent,
        priority=job.priority,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        next_run_at=job.next_run_at,
        locked_by=job.locked_by,
        lock_expires_at=job.lock_expires_at,
        heartbeat_at=job.heartbeat_at,
        last_error_code=job.last_error_code,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        updated_at=job.updated_at,
    )


def pipeline_event_payload(event: DocumentPipelineJobEvent) -> PipelineJobEventOut:
    return PipelineJobEventOut(
        id=event.id,
        job_id=event.job_id,
        document_id=event.document_id,
        event_type=event.event_type,
        step=event.step,
        message=event.message,
        payload=_json_dict(event.payload_json),
        created_at=event.created_at,
    )


def _active_job_for_document(db: Session, document_id: str) -> DocumentPipelineJob | None:
    return db.execute(
        select(DocumentPipelineJob)
        .where(DocumentPipelineJob.document_id == document_id)
        .where(DocumentPipelineJob.status.in_(ACTIVE_STATUSES))
        .order_by(DocumentPipelineJob.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _document_or_error(db: Session, document_id: str) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise _not_found("Document not found.")
    if document.status != "uploaded":
        raise _bad_request("Archived documents cannot be processed.")
    return document


def _create_pipeline_job(db: Session, document_id: str, *, force_new: bool = False, priority: int = 0) -> tuple[DocumentPipelineJob, bool]:
    _document_or_error(db, document_id)

    if not force_new:
        active_job = _active_job_for_document(db, document_id)
        if active_job is not None:
            return active_job, False

    now = _utc_now()
    job = DocumentPipelineJob(
        document_id=document_id,
        status="queued",
        current_step=None,
        steps_json=json.dumps(PIPELINE_STEPS),
        step_results_json="{}",
        cancel_requested=False,
        progress_percent=0,
        priority=priority,
        attempt_count=0,
        max_attempts=1,
        next_run_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.flush()
    _record_event(db, job, "queued", message="Pipeline job queued.")
    db.commit()
    db.refresh(job)
    wake_pipeline_worker()
    return job, True


def trigger_document_pipeline(db: Session, document_id: str) -> tuple[DocumentPipelineJob, bool]:
    return _create_pipeline_job(db, document_id)


def reprocess_document_pipeline(db: Session, document_id: str) -> tuple[DocumentPipelineJob, bool]:
    return _create_pipeline_job(db, document_id, force_new=True)


def get_latest_pipeline_job(db: Session, document_id: str) -> DocumentPipelineJob:
    if db.get(Document, document_id) is None:
        raise _not_found("Document not found.")
    job = db.execute(
        select(DocumentPipelineJob)
        .where(DocumentPipelineJob.document_id == document_id)
        .order_by(DocumentPipelineJob.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if job is None:
        raise _not_found("Pipeline job not found.")
    return job


def get_pipeline_job(db: Session, job_id: str) -> DocumentPipelineJob:
    job = db.get(DocumentPipelineJob, job_id)
    if job is None:
        raise _not_found("Pipeline job not found.")
    return job


def get_pipeline_job_events(db: Session, job_id: str) -> PipelineJobEventsOut:
    if db.get(DocumentPipelineJob, job_id) is None:
        raise _not_found("Pipeline job not found.")
    events = db.execute(
        select(DocumentPipelineJobEvent)
        .where(DocumentPipelineJobEvent.job_id == job_id)
        .order_by(DocumentPipelineJobEvent.created_at.asc())
    ).scalars().all()
    return PipelineJobEventsOut(
        items=[pipeline_event_payload(event) for event in events],
        total=len(events),
    )


def list_pipeline_events_after(
    db: Session,
    *,
    since_event_id: str | None = None,
    limit: int = 100,
) -> list[DocumentPipelineJobEvent]:
    query = select(DocumentPipelineJobEvent)
    order_by = text("rowid ASC")
    if since_event_id:
        cursor = db.get(DocumentPipelineJobEvent, since_event_id)
        if cursor is None:
            raise _bad_request("Pipeline event cursor not found.")
        cursor_rowid = db.execute(
            text("SELECT rowid FROM document_pipeline_job_events WHERE id = :event_id"),
            {"event_id": since_event_id},
        ).scalar_one_or_none()
        if cursor_rowid is None:
            raise _bad_request("Pipeline event cursor not found.")
        query = query.where(text("rowid > :cursor_rowid")).params(cursor_rowid=cursor_rowid)
    return list(
        db.execute(
            query.order_by(order_by).limit(max(1, min(limit, 100)))
        ).scalars().all()
    )


def format_pipeline_event_sse(event: DocumentPipelineJobEvent) -> str:
    payload = pipeline_event_payload(event).model_dump(mode="json")
    return (
        f"id: {event.id}\n"
        "event: pipeline_event\n"
        f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    )


def stream_pipeline_events(since_event_id: str | None = None):
    last_event_id = since_event_id
    while True:
        try:
            with SessionLocal() as db:
                events = list_pipeline_events_after(db, since_event_id=last_event_id, limit=50)
            if events:
                for event in events:
                    last_event_id = event.id
                    yield format_pipeline_event_sse(event)
            else:
                yield ": heartbeat\n\n"
        except HTTPException as error:
            detail = error.detail if isinstance(error.detail, dict) else {}
            data = {
                "code": detail.get("code", "BAD_REQUEST"),
                "message": detail.get("message", "Pipeline event stream failed."),
            }
            yield f"event: error\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            return
        time.sleep(max(0.5, settings.pipeline_poll_interval_seconds))


def list_pipeline_jobs(
    db: Session,
    *,
    limit: int,
    offset: int,
    status_filter: str | None = None,
) -> PipelineJobListOut:
    if status_filter and status_filter not in VALID_STATUSES:
        raise _bad_request("Invalid pipeline job status.")

    query = select(DocumentPipelineJob)
    count_query = select(func.count()).select_from(DocumentPipelineJob)
    if status_filter:
        query = query.where(DocumentPipelineJob.status == status_filter)
        count_query = count_query.where(DocumentPipelineJob.status == status_filter)

    total = db.execute(count_query).scalar_one()
    items = db.execute(
        query.order_by(DocumentPipelineJob.created_at.desc()).limit(limit).offset(offset)
    ).scalars().all()
    return PipelineJobListOut(
        items=[pipeline_job_payload(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


def _save_job_state(
    db: Session,
    job_id: str,
    *,
    status_value: str,
    current_step: str | None = None,
    step_results: dict | None = None,
    error_message: str | None = None,
    last_error_code: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    cancel_requested: bool | None = None,
    progress_percent: int | None = None,
    event_type: str | None = None,
    event_step: str | None = None,
    event_message: str | None = None,
    worker_id: str | None = None,
) -> DocumentPipelineJob | None:
    job = db.get(DocumentPipelineJob, job_id)
    if job is None:
        return None
    now = _utc_now()
    job.status = status_value
    job.current_step = current_step
    if step_results is not None:
        job.step_results_json = json.dumps(step_results, ensure_ascii=False)
    job.error_message = error_message
    if last_error_code is not None:
        job.last_error_code = last_error_code
    if started_at is not None:
        job.started_at = started_at
    if finished_at is not None:
        job.finished_at = finished_at
    if cancel_requested is not None:
        job.cancel_requested = cancel_requested
    if progress_percent is not None:
        job.progress_percent = max(0, min(100, progress_percent))
    if status_value == "running":
        job.heartbeat_at = now
        if worker_id:
            job.locked_by = worker_id
        job.lock_expires_at = _lock_expires_at(now)
    elif status_value in TERMINAL_STATUSES:
        job.locked_by = None
        job.lock_expires_at = None
        job.heartbeat_at = now
    job.updated_at = now
    if event_type:
        _record_event(db, job, event_type, step=event_step, message=event_message)
    db.commit()
    db.refresh(job)
    return job


def _job_cancel_requested(db: Session, job_id: str) -> bool:
    db.expire_all()
    job = db.get(DocumentPipelineJob, job_id)
    if job is None:
        return True
    return job.cancel_requested or job.status == "canceled"


def _mark_canceled(db: Session, job_id: str, step_results: dict | None = None) -> DocumentPipelineJob | None:
    return _save_job_state(
        db,
        job_id,
        status_value="canceled",
        current_step=None,
        step_results=step_results,
        error_message="Pipeline job canceled.",
        finished_at=_utc_now(),
        cancel_requested=True,
        event_type="canceled",
        event_message="Pipeline job canceled.",
    )


def _parse_step(db: Session, document_id: str) -> dict:
    result = parse_document(db, document_id)
    return {
        "status": result.status,
        "char_count": result.char_count,
        "truncated": result.truncated,
    }


def _chunk_step(db: Session, document_id: str) -> dict:
    result = chunk_document(db, document_id)
    return {
        "status": result.status,
        "chunk_count": result.chunk_count,
        "truncated": result.truncated,
    }


def _index_step(db: Session, document_id: str) -> dict:
    result = index_document(db, document_id)
    return {
        "status": result.status,
        "indexed_chunk_count": result.indexed_chunk_count,
        "provider": result.provider,
        "model": result.model,
    }


def _claim_specific_job(db: Session, job_id: str, worker_id: str) -> DocumentPipelineJob | None:
    job = db.get(DocumentPipelineJob, job_id)
    if job is None or job.status not in ACTIVE_STATUSES:
        return None
    now = _utc_now()
    if job.status == "running" and job.locked_by not in {None, worker_id}:
        expires = _as_utc(job.lock_expires_at)
        if expires is not None and expires > now:
            return None
    already_claimed_by_worker = job.status == "running" and job.locked_by == worker_id
    job.status = "running"
    job.locked_by = worker_id
    job.lock_expires_at = _lock_expires_at(now)
    job.heartbeat_at = now
    if not already_claimed_by_worker:
        job.attempt_count += 1
    if job.started_at is None:
        job.started_at = now
    job.updated_at = now
    _record_event(db, job, "claimed", message=f"Pipeline job claimed by {worker_id}.")
    db.commit()
    db.refresh(job)
    return job


def _claim_next_job(db: Session, worker_id: str) -> DocumentPipelineJob | None:
    now = _utc_now()
    job = db.execute(
        select(DocumentPipelineJob)
        .where(DocumentPipelineJob.status == "queued")
        .where(DocumentPipelineJob.next_run_at <= now)
        .order_by(DocumentPipelineJob.priority.desc(), DocumentPipelineJob.created_at.asc())
        .limit(1)
    ).scalar_one_or_none()
    if job is None:
        return None
    return _claim_specific_job(db, job.id, worker_id)


def run_pipeline_job(job_id: str, worker_id: str | None = None) -> None:
    runner_id = worker_id or "manual"
    with SessionLocal() as db:
        job = _claim_specific_job(db, job_id, runner_id)
        if job is None:
            return
        if job.cancel_requested:
            _mark_canceled(db, job_id)
            return

        _save_job_state(
            db,
            job_id,
            status_value="running",
            current_step="parse",
            step_results={},
            started_at=job.started_at or _utc_now(),
            progress_percent=STEP_START_PROGRESS["parse"],
            event_type="started",
            event_message="Pipeline job started.",
            worker_id=runner_id,
        )

        step_results: dict = {}
        steps = {
            "parse": _parse_step,
            "chunk": _chunk_step,
            "index": _index_step,
        }
        document_id = job.document_id

        for step_name in PIPELINE_STEPS:
            if _job_cancel_requested(db, job_id):
                _mark_canceled(db, job_id, step_results)
                return

            _save_job_state(
                db,
                job_id,
                status_value="running",
                current_step=step_name,
                step_results=step_results,
                progress_percent=STEP_START_PROGRESS[step_name],
                event_type="step_started",
                event_step=step_name,
                event_message=f"{step_name} started.",
                worker_id=runner_id,
            )
            try:
                step_results[step_name] = steps[step_name](db, document_id)
            except Exception as error:
                db.rollback()
                message = _short_error(error)
                code = _error_code(error)
                logger.exception(
                    "Document pipeline step failed: job_id=%s document_id=%s step=%s",
                    job_id,
                    document_id,
                    step_name,
                )
                _save_job_state(
                    db,
                    job_id,
                    status_value="failed",
                    current_step=step_name,
                    step_results=step_results,
                    error_message=message,
                    last_error_code=code,
                    finished_at=_utc_now(),
                    event_type="failed",
                    event_step=step_name,
                    event_message=message,
                )
                return

            _save_job_state(
                db,
                job_id,
                status_value="running",
                current_step=step_name,
                step_results=step_results,
                progress_percent=STEP_DONE_PROGRESS[step_name],
                event_type="step_completed",
                event_step=step_name,
                event_message=f"{step_name} completed.",
                worker_id=runner_id,
            )
            if _job_cancel_requested(db, job_id):
                _mark_canceled(db, job_id, step_results)
                return

        _save_job_state(
            db,
            job_id,
            status_value="succeeded",
            current_step=None,
            step_results=step_results,
            error_message=None,
            last_error_code=None,
            finished_at=_utc_now(),
            progress_percent=100,
            event_type="succeeded",
            event_message="Pipeline job succeeded.",
        )


class PipelineWorker:
    def __init__(self) -> None:
        self.worker_id = f"pipeline-worker-{uuid4().hex[:12]}"
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="document-pipeline-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def wake(self) -> None:
        self._wake_event.set()

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                recover_stale_pipeline_jobs()
                with SessionLocal() as db:
                    job = _claim_next_job(db, self.worker_id)
                    job_id = job.id if job is not None else None
                if job_id:
                    run_pipeline_job(job_id, self.worker_id)
                    continue
            except Exception:
                logger.exception("Pipeline worker loop failed.")
            self._wake_event.wait(timeout=max(0.2, settings.pipeline_poll_interval_seconds))
            self._wake_event.clear()


_WORKER_LOCK = threading.Lock()
_WORKER: PipelineWorker | None = None


def start_pipeline_worker() -> PipelineWorker:
    global _WORKER
    with _WORKER_LOCK:
        if _WORKER is None:
            _WORKER = PipelineWorker()
        _WORKER.start()
        return _WORKER


def stop_pipeline_worker() -> None:
    with _WORKER_LOCK:
        if _WORKER is not None:
            _WORKER.stop()


def wake_pipeline_worker() -> None:
    worker = start_pipeline_worker()
    worker.wake()


def worker_snapshot() -> dict:
    worker = _WORKER
    return {
        "worker_running": bool(worker and worker.running),
        "worker_id": worker.worker_id if worker else None,
        "worker_concurrency": _worker_concurrency(),
    }


def recover_stale_pipeline_jobs() -> int:
    with SessionLocal() as db:
        now = _utc_now()
        jobs = db.execute(
            select(DocumentPipelineJob).where(
                DocumentPipelineJob.status == "running",
                or_(
                    DocumentPipelineJob.lock_expires_at.is_(None),
                    DocumentPipelineJob.lock_expires_at <= now,
                ),
            )
        ).scalars().all()
        for job in jobs:
            job.status = "queued"
            job.current_step = None
            job.locked_by = None
            job.lock_expires_at = None
            job.heartbeat_at = now
            job.error_message = RECOVERED_MESSAGE
            job.updated_at = now
            _record_event(db, job, "recovered", message=RECOVERED_MESSAGE)
        db.commit()
        if jobs:
            wake_pipeline_worker()
        return len(jobs)


def fail_interrupted_pipeline_jobs() -> int:
    return recover_stale_pipeline_jobs()


def cancel_pipeline_job(db: Session, job_id: str) -> DocumentPipelineJob:
    job = db.get(DocumentPipelineJob, job_id)
    if job is None:
        raise _not_found("Pipeline job not found.")

    now = _utc_now()
    if job.status == "queued":
        job.status = "canceled"
        job.cancel_requested = True
        job.current_step = None
        job.error_message = "Pipeline job canceled."
        job.finished_at = now
        job.updated_at = now
        _record_event(db, job, "canceled", message="Pipeline job canceled before running.")
        db.commit()
        db.refresh(job)
        return job

    if job.status == "running":
        job.cancel_requested = True
        job.updated_at = now
        _record_event(db, job, "cancel_requested", step=job.current_step, message="Cancel requested.")
        db.commit()
        db.refresh(job)
        return job

    return job


def retry_pipeline_job(db: Session, job_id: str) -> DocumentPipelineJob:
    job = db.get(DocumentPipelineJob, job_id)
    if job is None:
        raise _not_found("Pipeline job not found.")
    if job.status not in {"failed", "canceled"}:
        raise _bad_request("Only failed or canceled pipeline jobs can be retried.")

    new_job, _created = _create_pipeline_job(db, job.document_id, force_new=True, priority=job.priority)
    return new_job


def update_pipeline_priority(db: Session, job_id: str, priority: int) -> DocumentPipelineJob:
    job = db.get(DocumentPipelineJob, job_id)
    if job is None:
        raise _not_found("Pipeline job not found.")
    if job.status != "queued":
        raise _bad_request("Only queued pipeline jobs can change priority.")
    job.priority = priority
    job.updated_at = _utc_now()
    _record_event(db, job, "priority_updated", message=f"Priority updated to {priority}.", payload={"priority": priority})
    db.commit()
    db.refresh(job)
    wake_pipeline_worker()
    return job


def batch_process_missing_documents(db: Session, project_id: str | None = None) -> PipelineBatchOut:
    if project_id and db.get(Project, project_id) is None:
        raise _bad_request("Project not found.")

    query = select(Document).where(Document.status == "uploaded")
    if project_id:
        query = query.where(Document.project_id == project_id)

    jobs: list[DocumentPipelineJob] = []
    documents = db.execute(query.order_by(Document.created_at.desc())).scalars().all()
    for document in documents:
        if _active_job_for_document(db, document.id) is not None:
            continue

        embedding_result = db.get(DocumentEmbeddingResult, document.id)
        if embedding_result is not None and embedding_result.status == "indexed":
            continue

        job, created = _create_pipeline_job(db, document.id)
        if created:
            jobs.append(job)

    return PipelineBatchOut(
        items=[pipeline_job_payload(job) for job in jobs],
        total=len(jobs),
    )


def _select_pipeline_batch_jobs(
    db: Session,
    *,
    job_ids: list[str] | None = None,
    status_filter: str | None = None,
    project_id: str | None = None,
) -> tuple[list[DocumentPipelineJob], int]:
    if not job_ids and not status_filter:
        raise _bad_request("Provide job_ids or status.")
    if status_filter and status_filter not in {"queued", "running", "failed", "canceled"}:
        raise _bad_request("Invalid pipeline job status.")
    if project_id and db.get(Project, project_id) is None:
        raise _bad_request("Project not found.")

    normalized_ids = list(dict.fromkeys(job_ids or []))
    if len(normalized_ids) > 100:
        raise _bad_request("At most 100 pipeline jobs can be processed at once.")

    query = select(DocumentPipelineJob)
    if project_id:
        query = query.join(Document, Document.id == DocumentPipelineJob.document_id).where(Document.project_id == project_id)
    if normalized_ids:
        query = query.where(DocumentPipelineJob.id.in_(normalized_ids))
    if status_filter:
        query = query.where(DocumentPipelineJob.status == status_filter)

    jobs = list(
        db.execute(
            query.order_by(DocumentPipelineJob.created_at.desc()).limit(100)
        ).scalars().all()
    )
    missing_count = max(0, len(normalized_ids) - len({job.id for job in jobs})) if normalized_ids else 0
    return jobs, missing_count


def batch_cancel_pipeline_jobs(
    db: Session,
    *,
    job_ids: list[str] | None = None,
    status_filter: str | None = None,
    project_id: str | None = None,
) -> PipelineBatchActionOut:
    jobs, skipped = _select_pipeline_batch_jobs(
        db,
        job_ids=job_ids,
        status_filter=status_filter,
        project_id=project_id,
    )
    acted_jobs: list[DocumentPipelineJob] = []
    for job in jobs:
        if job.status not in {"queued", "running"}:
            skipped += 1
            continue
        acted_jobs.append(cancel_pipeline_job(db, job.id))

    return PipelineBatchActionOut(
        items=[pipeline_job_payload(job) for job in acted_jobs],
        total=len(acted_jobs),
        acted=len(acted_jobs),
        skipped=skipped,
    )


def batch_retry_pipeline_jobs(
    db: Session,
    *,
    job_ids: list[str] | None = None,
    status_filter: str | None = None,
    project_id: str | None = None,
) -> PipelineBatchActionOut:
    jobs, skipped = _select_pipeline_batch_jobs(
        db,
        job_ids=job_ids,
        status_filter=status_filter,
        project_id=project_id,
    )
    new_jobs: list[DocumentPipelineJob] = []
    for job in jobs:
        if job.status not in {"failed", "canceled"}:
            skipped += 1
            continue
        try:
            new_jobs.append(retry_pipeline_job(db, job.id))
        except HTTPException:
            skipped += 1

    return PipelineBatchActionOut(
        items=[pipeline_job_payload(job) for job in new_jobs],
        total=len(new_jobs),
        acted=len(new_jobs),
        skipped=skipped,
    )


def _provider_check(provider: str, model: str, *, requires_key: bool) -> ProviderCheckOut:
    normalized = provider.strip().lower()
    if normalized == "fake":
        return ProviderCheckOut(provider=provider, model=model, configured=True, reason=None)
    if normalized != "openai":
        return ProviderCheckOut(provider=provider, model=model, configured=False, reason="Unsupported provider.")
    if requires_key and not settings.openai_api_key:
        return ProviderCheckOut(provider=provider, model=model, configured=False, reason="OPENAI_API_KEY is not configured.")
    if not settings.openai_base_url:
        return ProviderCheckOut(provider=provider, model=model, configured=False, reason="OPENAI_BASE_URL is not configured.")
    if not model:
        return ProviderCheckOut(provider=provider, model=model, configured=False, reason="Model is not configured.")
    return ProviderCheckOut(provider=provider, model=model, configured=True, reason=None)


def get_providers_status() -> ProvidersStatusOut:
    llm = _provider_check(settings.llm_provider, settings.openai_model, requires_key=True)
    embedding = _provider_check(settings.embedding_provider, settings.embedding_model, requires_key=True)
    return ProvidersStatusOut(
        llm=llm,
        embedding=embedding,
        openai_base_url_configured=bool(settings.openai_base_url),
        chroma_collection_name=settings.chroma_collection_name,
    )


def get_pipeline_status(db: Session) -> PipelineStatusOut:
    counts = {status_name: 0 for status_name in VALID_STATUSES}
    rows = db.execute(
        select(DocumentPipelineJob.status, func.count()).group_by(DocumentPipelineJob.status)
    ).all()
    for status_name, count in rows:
        if status_name in counts:
            counts[status_name] = count

    recent_failures = db.execute(
        select(DocumentPipelineJob)
        .where(DocumentPipelineJob.status == "failed")
        .order_by(DocumentPipelineJob.updated_at.desc())
        .limit(5)
    ).scalars().all()
    provider_status = get_providers_status()
    now = _utc_now()
    stale_running_count = db.execute(
        select(func.count()).select_from(DocumentPipelineJob).where(
            and_(
                DocumentPipelineJob.status == "running",
                or_(
                    DocumentPipelineJob.lock_expires_at.is_(None),
                    DocumentPipelineJob.lock_expires_at <= now,
                ),
            )
        )
    ).scalar_one()
    oldest_queued_at = db.execute(
        select(func.min(DocumentPipelineJob.created_at)).where(DocumentPipelineJob.status == "queued")
    ).scalar_one()
    worker = worker_snapshot()
    return PipelineStatusOut(
        queued_count=counts["queued"],
        running_count=counts["running"],
        succeeded_count=counts["succeeded"],
        failed_count=counts["failed"],
        canceled_count=counts["canceled"],
        active_count=counts["queued"] + counts["running"],
        recent_failures=[pipeline_job_payload(job) for job in recent_failures],
        provider_configured=provider_status.embedding.configured,
        worker_running=worker["worker_running"],
        worker_id=worker["worker_id"],
        worker_concurrency=worker["worker_concurrency"],
        stale_running_count=stale_running_count,
        oldest_queued_at=oldest_queued_at,
    )
