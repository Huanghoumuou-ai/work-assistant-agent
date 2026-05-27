from __future__ import annotations

import time
from uuid import uuid4

from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from backend.app.core.config import settings
from backend.app.db.models import DocumentChunkResult, DocumentEmbeddingResult, DocumentParseResult, DocumentPipelineJob, DocumentPipelineJobEvent
from backend.app.db.init_db import init_db
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.services import pipeline_service
from backend.app.services.pipeline_service import fail_interrupted_pipeline_jobs


def _use_fake_embedding(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "embedding_provider", "fake")
    monkeypatch.setattr(settings, "chroma_collection_name", f"pipeline_{uuid4().hex}")


def _upload(name: str = "pipeline.md", content: bytes = b"pipeline content", project_id: str | None = None) -> dict:
    with TestClient(app) as client:
        data = {"project_id": project_id} if project_id else None
        response = client.post("/api/upload", files={"file": (name, content, "text/markdown")}, data=data)
    assert response.status_code == 200
    return response.json()["data"]


def _trigger(document_id: str):
    with TestClient(app) as client:
        return client.post(f"/api/documents/{document_id}/pipeline")


def _wait_job(job_id: str, timeout_seconds: float = 10) -> DocumentPipelineJob:
    deadline = time.time() + timeout_seconds
    last_job: DocumentPipelineJob | None = None
    while time.time() < deadline:
        with SessionLocal() as db:
            job = db.get(DocumentPipelineJob, job_id)
            if job is not None:
                db.expunge(job)
                last_job = job
                if job.status in {"succeeded", "failed", "canceled"}:
                    return job
        time.sleep(0.05)
    assert last_job is not None
    raise AssertionError(f"Pipeline job did not finish: {last_job.status}")


def test_pipeline_success_processes_document(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_embedding(monkeypatch)
    document = _upload("pipeline-success.md", b"alpha beta gamma")

    response = _trigger(document["id"])

    assert response.status_code == 202
    data = response.json()["data"]
    assert data["status"] in {"queued", "running", "succeeded"}
    assert data["cancel_requested"] is False
    assert 0 <= data["progress_percent"] <= 100
    job = _wait_job(data["id"])
    assert job.status == "succeeded"
    assert job.current_step is None
    assert job.progress_percent == 100

    with SessionLocal() as db:
        assert db.get(DocumentParseResult, document["id"]).status == "parsed"
        assert db.get(DocumentChunkResult, document["id"]).status == "chunked"
        assert db.get(DocumentEmbeddingResult, document["id"]).status == "indexed"

    with TestClient(app) as client:
        latest = client.get(f"/api/documents/{document['id']}/pipeline")
        listing = client.get("/api/pipeline/jobs?limit=50&offset=0")

    assert latest.status_code == 200
    assert latest.json()["data"]["id"] == job.id
    assert listing.status_code == 200
    assert any(item["id"] == job.id for item in listing.json()["data"]["items"])

    with TestClient(app) as client:
        detail = client.get(f"/api/pipeline/jobs/{job.id}")
        events = client.get(f"/api/pipeline/jobs/{job.id}/events")

    assert detail.status_code == 200
    detail_data = detail.json()["data"]
    assert detail_data["attempt_count"] >= 1
    assert detail_data["priority"] == 0
    assert detail_data["locked_by"] is None
    assert detail_data["last_error_code"] is None
    assert events.status_code == 200
    event_types = [item["event_type"] for item in events.json()["data"]["items"]]
    assert "queued" in event_types
    assert "step_started" in event_types
    assert "step_completed" in event_types
    assert "succeeded" in event_types


def test_active_job_retrigger_returns_existing_job(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_embedding(monkeypatch)
    document = _upload("pipeline-active.md", b"active")
    with SessionLocal() as db:
        active = DocumentPipelineJob(
            document_id=document["id"],
            status="queued",
            next_run_at=pipeline_service._utc_now() + pipeline_service.timedelta(seconds=300),
        )
        db.add(active)
        db.commit()
        active_id = active.id

    response = _trigger(document["id"])

    assert response.status_code == 202
    assert response.json()["data"]["id"] == active_id


def test_failed_job_can_be_retriggered(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_embedding(monkeypatch)
    document = _upload("pipeline-retry.md", b"retry")
    with SessionLocal() as db:
        failed = DocumentPipelineJob(document_id=document["id"], status="failed", error_message="old failure")
        db.add(failed)
        db.commit()
        failed_id = failed.id

    response = _trigger(document["id"])

    assert response.status_code == 202
    assert response.json()["data"]["id"] != failed_id
    job = _wait_job(response.json()["data"]["id"])
    assert job.status == "succeeded"


def test_archived_document_pipeline_returns_400(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_embedding(monkeypatch)
    document = _upload("pipeline-archived.md", b"archived")
    with TestClient(app) as client:
        assert client.patch(f"/api/documents/{document['id']}/status", json={"status": "archived"}).status_code == 200

    response = _trigger(document["id"])

    assert response.status_code == 400


def test_parse_failure_marks_job_failed_and_stops(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_embedding(monkeypatch)
    document = _upload("pipeline-parse-fail.md", b"parse fail")

    def fail_parse(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "code": "BAD_REQUEST", "message": "forced parse failure", "data": None},
        )

    monkeypatch.setattr(pipeline_service, "parse_document", fail_parse)
    response = _trigger(document["id"])
    job = _wait_job(response.json()["data"]["id"])

    assert job.status == "failed"
    assert job.current_step == "parse"
    assert job.error_message == "forced parse failure"
    with SessionLocal() as db:
        assert db.get(DocumentChunkResult, document["id"]) is None
        assert db.get(DocumentEmbeddingResult, document["id"]) is None


def test_chunk_failure_marks_job_failed_and_stops_before_index(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_embedding(monkeypatch)
    document = _upload("pipeline-chunk-fail.md", b"chunk fail")

    def fail_chunk(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "code": "BAD_REQUEST", "message": "forced chunk failure", "data": None},
        )

    monkeypatch.setattr(pipeline_service, "chunk_document", fail_chunk)
    response = _trigger(document["id"])
    job = _wait_job(response.json()["data"]["id"])

    assert job.status == "failed"
    assert job.current_step == "chunk"
    assert job.error_message == "forced chunk failure"
    with SessionLocal() as db:
        assert db.get(DocumentParseResult, document["id"]).status == "parsed"
        assert db.get(DocumentEmbeddingResult, document["id"]) is None


def test_index_failure_marks_job_failed_after_parse_and_chunk(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_embedding(monkeypatch)
    document = _upload("pipeline-index-fail.md", b"index fail")

    def fail_index(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "code": "BAD_REQUEST", "message": "forced index failure", "data": None},
        )

    monkeypatch.setattr(pipeline_service, "index_document", fail_index)
    response = _trigger(document["id"])
    job = _wait_job(response.json()["data"]["id"])

    assert job.status == "failed"
    assert job.current_step == "index"
    assert job.error_message == "forced index failure"
    with SessionLocal() as db:
        assert db.get(DocumentParseResult, document["id"]).status == "parsed"
        assert db.get(DocumentChunkResult, document["id"]).status == "chunked"
        assert db.get(DocumentEmbeddingResult, document["id"]) is None


def test_startup_recovery_requeues_stale_running_jobs(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_embedding(monkeypatch)
    document = _upload("pipeline-interrupted.md", b"interrupted")
    with SessionLocal() as db:
        queued = DocumentPipelineJob(
            document_id=document["id"],
            status="queued",
            next_run_at=pipeline_service._utc_now() + pipeline_service.timedelta(seconds=300),
        )
        running = DocumentPipelineJob(document_id=document["id"], status="running", current_step="index", locked_by="dead-worker")
        db.add_all([queued, running])
        db.commit()
        queued_id = queued.id
        running_id = running.id

    count = fail_interrupted_pipeline_jobs()

    assert count >= 1
    with SessionLocal() as db:
        queued_job = db.get(DocumentPipelineJob, queued_id)
        running_job = db.get(DocumentPipelineJob, running_id)
        assert queued_job is not None and queued_job.status == "queued"
        assert running_job is not None and running_job.status == "queued"
        assert "recovered" in (running_job.error_message or "")


def test_queued_job_cancel_sets_canceled(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_embedding(monkeypatch)
    document = _upload("pipeline-cancel-queued.md", b"cancel queued")
    with SessionLocal() as db:
        queued = DocumentPipelineJob(
            document_id=document["id"],
            status="queued",
            progress_percent=0,
            next_run_at=pipeline_service._utc_now() + pipeline_service.timedelta(seconds=300),
        )
        db.add(queued)
        db.commit()
        job_id = queued.id

    with TestClient(app) as client:
        response = client.post(f"/api/pipeline/jobs/{job_id}/cancel")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "canceled"
    assert data["cancel_requested"] is True
    assert data["progress_percent"] == 0


def test_running_job_cancel_requests_stop(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_embedding(monkeypatch)
    document = _upload("pipeline-cancel-running.md", b"cancel running")
    with SessionLocal() as db:
        running = DocumentPipelineJob(
            document_id=document["id"],
            status="running",
            current_step="parse",
            progress_percent=10,
            locked_by="active-worker",
            lock_expires_at=pipeline_service._utc_now() + pipeline_service.timedelta(seconds=300),
        )
        db.add(running)
        db.commit()
        job_id = running.id

    with TestClient(app) as client:
        response = client.post(f"/api/pipeline/jobs/{job_id}/cancel")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "running"
    assert data["cancel_requested"] is True
    assert data["progress_percent"] == 10


def test_running_job_stops_after_current_step_when_cancel_requested(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_embedding(monkeypatch)
    document = _upload("pipeline-stop-after-step.md", b"stop after step")
    with SessionLocal() as db:
        queued = DocumentPipelineJob(
            document_id=document["id"],
            status="queued",
            progress_percent=0,
            next_run_at=pipeline_service._utc_now() + pipeline_service.timedelta(seconds=300),
        )
        db.add(queued)
        db.commit()
        job_id = queued.id

    original_parse = pipeline_service.parse_document

    def parse_then_cancel(db, document_id):  # type: ignore[no-untyped-def]
        result = original_parse(db, document_id)
        job = db.get(DocumentPipelineJob, job_id)
        job.cancel_requested = True
        db.commit()
        return result

    monkeypatch.setattr(pipeline_service, "parse_document", parse_then_cancel)
    pipeline_service.run_pipeline_job(job_id)

    with SessionLocal() as db:
        job = db.get(DocumentPipelineJob, job_id)
        assert job.status == "canceled"
        assert job.progress_percent == 35
        assert db.get(DocumentParseResult, document["id"]).status == "parsed"
        assert db.get(DocumentChunkResult, document["id"]) is None
        assert db.get(DocumentEmbeddingResult, document["id"]) is None


def test_priority_update_only_allows_queued_jobs(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_embedding(monkeypatch)
    document = _upload("pipeline-priority.md", b"priority")
    with SessionLocal() as db:
        queued = DocumentPipelineJob(
            document_id=document["id"],
            status="queued",
            progress_percent=0,
            next_run_at=pipeline_service._utc_now() + pipeline_service.timedelta(seconds=300),
        )
        running = DocumentPipelineJob(
            document_id=document["id"],
            status="running",
            current_step="parse",
            locked_by="active-worker",
            lock_expires_at=pipeline_service._utc_now() + pipeline_service.timedelta(seconds=300),
        )
        db.add_all([queued, running])
        db.commit()
        queued_id = queued.id
        running_id = running.id

    with TestClient(app) as client:
        queued_response = client.post(f"/api/pipeline/jobs/{queued_id}/priority", json={"priority": 7})
        running_response = client.post(f"/api/pipeline/jobs/{running_id}/priority", json={"priority": 9})

    assert queued_response.status_code == 200
    assert queued_response.json()["data"]["priority"] == 7
    assert running_response.status_code == 400


def test_retry_failed_and_canceled_jobs_create_new_job(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_embedding(monkeypatch)
    document = _upload("pipeline-retry-api.md", b"retry api")
    with SessionLocal() as db:
        failed = DocumentPipelineJob(document_id=document["id"], status="failed", error_message="old")
        canceled = DocumentPipelineJob(document_id=document["id"], status="canceled", cancel_requested=True)
        db.add_all([failed, canceled])
        db.commit()
        failed_id = failed.id
        canceled_id = canceled.id

    with TestClient(app) as client:
        failed_response = client.post(f"/api/pipeline/jobs/{failed_id}/retry")
        canceled_response = client.post(f"/api/pipeline/jobs/{canceled_id}/retry")

    assert failed_response.status_code == 202
    assert failed_response.json()["data"]["id"] != failed_id
    assert canceled_response.status_code == 202
    assert canceled_response.json()["data"]["id"] != canceled_id


def test_succeeded_job_reprocess_creates_new_job(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_embedding(monkeypatch)
    document = _upload("pipeline-reprocess.md", b"reprocess")
    with SessionLocal() as db:
        succeeded = DocumentPipelineJob(document_id=document["id"], status="succeeded", progress_percent=100)
        db.add(succeeded)
        db.commit()
        old_id = succeeded.id

    with TestClient(app) as client:
        response = client.post(f"/api/documents/{document['id']}/pipeline/reprocess")

    assert response.status_code == 202
    assert response.json()["data"]["id"] != old_id


def test_archived_document_reprocess_returns_400(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_embedding(monkeypatch)
    document = _upload("pipeline-reprocess-archived.md", b"archived")
    with TestClient(app) as client:
        client.patch(f"/api/documents/{document['id']}/status", json={"status": "archived"})
        response = client.post(f"/api/documents/{document['id']}/pipeline/reprocess")

    assert response.status_code == 400


def test_batch_process_missing_skips_indexed_and_active_documents(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_embedding(monkeypatch)
    with TestClient(app) as client:
        project_response = client.post("/api/projects", json={"name": f"pipeline batch {uuid4().hex}", "description": None})
    project_id = project_response.json()["data"]["id"]
    missing = _upload("pipeline-missing.md", b"missing", project_id=project_id)
    indexed = _upload("pipeline-indexed.md", b"indexed", project_id=project_id)
    active = _upload("pipeline-active-skip.md", b"active", project_id=project_id)
    now = pipeline_service._utc_now()
    with SessionLocal() as db:
        db.add(
            DocumentEmbeddingResult(
                document_id=indexed["id"],
                status="indexed",
                provider="fake",
                model=settings.embedding_model,
                embedding_dimension=8,
                chunk_set_sha256="a" * 64,
                indexed_chunk_count=1,
                vector_collection=settings.chroma_collection_name,
                indexed_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            DocumentPipelineJob(
                document_id=active["id"],
                status="queued",
                next_run_at=pipeline_service._utc_now() + pipeline_service.timedelta(seconds=300),
            )
        )
        db.commit()

    with TestClient(app) as client:
        response = client.post(f"/api/pipeline/batch/process-missing?project_id={project_id}")

    assert response.status_code == 202
    items = response.json()["data"]["items"]
    assert {item["document_id"] for item in items} == {missing["id"]}


def test_batch_cancel_handles_queued_running_and_skips_terminal(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_embedding(monkeypatch)
    document = _upload("pipeline-batch-cancel.md", b"batch cancel")
    with SessionLocal() as db:
        queued = DocumentPipelineJob(
            document_id=document["id"],
            status="queued",
            progress_percent=0,
            next_run_at=pipeline_service._utc_now() + pipeline_service.timedelta(seconds=300),
        )
        running = DocumentPipelineJob(
            document_id=document["id"],
            status="running",
            current_step="index",
            progress_percent=65,
            locked_by="active-worker",
            lock_expires_at=pipeline_service._utc_now() + pipeline_service.timedelta(seconds=300),
        )
        failed = DocumentPipelineJob(document_id=document["id"], status="failed", error_message="old")
        db.add_all([queued, running, failed])
        db.commit()
        job_ids = [queued.id, running.id, failed.id]

    with TestClient(app) as client:
        response = client.post("/api/pipeline/batch/cancel", json={"job_ids": job_ids})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["acted"] == 2
    assert data["skipped"] == 1
    statuses = {item["id"]: item for item in data["items"]}
    assert statuses[queued.id]["status"] == "canceled"
    assert statuses[running.id]["status"] == "running"
    assert statuses[running.id]["cancel_requested"] is True


def test_batch_retry_creates_jobs_for_failed_and_canceled_only(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_embedding(monkeypatch)
    document = _upload("pipeline-batch-retry.md", b"batch retry")
    with SessionLocal() as db:
        failed = DocumentPipelineJob(document_id=document["id"], status="failed", error_message="old")
        canceled = DocumentPipelineJob(document_id=document["id"], status="canceled", cancel_requested=True)
        succeeded = DocumentPipelineJob(document_id=document["id"], status="succeeded", progress_percent=100)
        db.add_all([failed, canceled, succeeded])
        db.commit()
        old_ids = {failed.id, canceled.id, succeeded.id}

    with TestClient(app) as client:
        response = client.post("/api/pipeline/batch/retry", json={"job_ids": list(old_ids)})

    assert response.status_code == 202
    data = response.json()["data"]
    assert data["acted"] == 2
    assert data["skipped"] == 1
    assert {item["status"] for item in data["items"]}.issubset({"queued", "running"})
    assert not ({item["id"] for item in data["items"]} & old_ids)


def test_pipeline_event_cursor_returns_events_after_id(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_embedding(monkeypatch)
    document = _upload("pipeline-events-cursor.md", b"events")
    with SessionLocal() as db:
        job = DocumentPipelineJob(document_id=document["id"], status="failed", error_message="manual event test")
        db.add(job)
        db.flush()
        pipeline_service._record_event(db, job, "first", message="first")
        pipeline_service._record_event(db, job, "second", message="second")
        db.commit()
        events = db.query(DocumentPipelineJobEvent).filter(DocumentPipelineJobEvent.job_id == job.id).order_by(DocumentPipelineJobEvent.created_at.asc()).all()
        first_id = events[0].id

    with SessionLocal() as db:
        after = pipeline_service.list_pipeline_events_after(db, since_event_id=first_id, limit=10)

    assert [event.event_type for event in after] == ["second"]
    sse = pipeline_service.format_pipeline_event_sse(after[0])
    assert "event: pipeline_event" in sse
    assert after[0].id in sse


def test_pipeline_and_provider_status_do_not_expose_api_key(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "openai_api_key", "sk-secret-for-test")
    with TestClient(app) as client:
        provider_response = client.get("/api/providers/status")
        pipeline_response = client.get("/api/pipeline/status")

    assert provider_response.status_code == 200
    assert pipeline_response.status_code == 200
    assert "sk-secret-for-test" not in provider_response.text
    assert "sk-secret-for-test" not in pipeline_response.text
    assert "provider_configured" in pipeline_response.json()["data"]


def test_pipeline_schema_validation_detects_missing_phase_15_columns() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE document_pipeline_jobs (
                    id VARCHAR(36) PRIMARY KEY,
                    document_id VARCHAR(36) NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    current_step VARCHAR(20),
                    steps_json TEXT NOT NULL,
                    step_results_json TEXT NOT NULL,
                    error_message TEXT,
                    created_at DATETIME NOT NULL,
                    started_at DATETIME,
                    finished_at DATETIME,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )

    try:
        init_db(bind=engine)
    except RuntimeError as error:
        assert "cancel_requested" in str(error)
        assert "progress_percent" in str(error)
    else:
        raise AssertionError("Expected incompatible document_pipeline_jobs schema to be rejected.")
