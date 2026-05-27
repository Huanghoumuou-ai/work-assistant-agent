from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from backend.app.dependencies import get_db
from backend.app.db.models import Document, DocumentChunkResult, DocumentEmbeddingResult, DocumentParseResult
from backend.app.schemas.document import (
    ChunkListOut,
    ChunkContentOut,
    ChunkMetaOut,
    ChunkResultOut,
    DocumentChunksOut,
    DocumentListOut,
    DocumentOut,
    EmbeddingResultOut,
    IndexCollectionsOut,
    IndexDiagnosticsOut,
    IndexResetOut,
    IndexStatusOut,
    ParseResultOut,
    PipelineBatchActionOut,
    PipelineBatchOut,
    ProviderDiagnosticHistoryOut,
    PipelineJobEventsOut,
    PipelineJobOut,
    PipelineStatusOut,
    ProviderDiagnosticOut,
    ProvidersStatusOut,
)
from backend.app.schemas.requests import DocumentStatusUpdate, IndexResetRequest, PipelineBatchActionRequest, PipelinePriorityUpdate, TextDocumentCreate
from backend.app.services.chunk_service import chunk_document, get_chunk_content, get_document_chunks, list_chunks
from backend.app.services.diagnostics_service import (
    get_index_diagnostics,
    get_provider_diagnostic_history,
    list_index_collections,
    record_embedding_provider_failure,
    record_llm_provider_failure,
    record_provider_diagnostic_success,
    reset_current_index,
    test_embedding_provider,
    test_llm_provider,
)
from backend.app.services.document_service import delete_document, list_documents, save_text_document, save_uploaded_document, update_document_status
from backend.app.services.index_service import get_index_result, get_index_status, index_document
from backend.app.services.parse_service import get_parse_result, parse_document
from backend.app.services.pipeline_service import (
    batch_process_missing_documents,
    batch_cancel_pipeline_jobs,
    batch_retry_pipeline_jobs,
    cancel_pipeline_job,
    get_pipeline_job,
    get_pipeline_job_events,
    get_latest_pipeline_job,
    get_pipeline_status,
    get_providers_status,
    stream_pipeline_events,
    list_pipeline_jobs,
    pipeline_job_payload,
    reprocess_document_pipeline,
    retry_pipeline_job,
    trigger_document_pipeline,
    update_pipeline_priority,
)


router = APIRouter()


def _parse_result_payload(result: DocumentParseResult | None) -> dict | None:
    if result is None:
        return None
    return ParseResultOut.model_validate(result).model_dump(mode="json")


def _chunk_result_payload(result: DocumentChunkResult | None) -> dict | None:
    if result is None:
        return None
    return ChunkResultOut.model_validate(result).model_dump(mode="json")


def _embedding_result_payload(result: DocumentEmbeddingResult | None) -> dict | None:
    if result is None:
        return None
    return EmbeddingResultOut.model_validate(result).model_dump(mode="json")


def _document_payload(db: Session, document: Document) -> dict:
    payload = DocumentOut.model_validate(document).model_dump(mode="json")
    payload["parse_result"] = _parse_result_payload(db.get(DocumentParseResult, document.id))
    payload["chunk_result"] = _chunk_result_payload(db.get(DocumentChunkResult, document.id))
    payload["embedding_result"] = _embedding_result_payload(db.get(DocumentEmbeddingResult, document.id))
    return payload


@router.post("/upload")
async def upload_document(
    file: Annotated[UploadFile, File()],
    project_id: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
) -> dict:
    if project_id == "":
        project_id = None
    document = await save_uploaded_document(db, file, project_id=project_id)
    return {
        "success": True,
        "code": "OK",
        "message": "File uploaded.",
        "data": _document_payload(db, document),
    }


@router.post("/documents/text")
async def create_text_document(payload: TextDocumentCreate, db: Session = Depends(get_db)) -> dict:
    project_id = payload.project_id or None
    document = save_text_document(
        db,
        content=payload.content,
        title=payload.title,
        project_id=project_id,
    )
    return {
        "success": True,
        "code": "OK",
        "message": "Text document created.",
        "data": _document_payload(db, document),
    }


@router.get("/documents")
async def get_documents(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    project_id: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    items, total = list_documents(
        db,
        limit=limit,
        offset=offset,
        project_id=project_id,
        status_filter=status,
    )
    payload = DocumentListOut(
        items=[DocumentOut.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )
    payload_data = payload.model_dump(mode="json")
    payload_data["items"] = [_document_payload(db, item) for item in items]
    return {
        "success": True,
        "code": "OK",
        "message": "Documents loaded.",
        "data": payload_data,
    }


@router.get("/documents/{document_id}")
async def get_document(document_id: str, db: Session = Depends(get_db)) -> dict:
    document = db.get(Document, document_id)
    if document is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "success": False,
                "code": "NOT_FOUND",
                "message": "Document not found.",
                "data": None,
            },
        )
    return {
        "success": True,
        "code": "OK",
        "message": "Document loaded.",
        "data": _document_payload(db, document),
    }


@router.post("/documents/{document_id}/pipeline", status_code=status.HTTP_202_ACCEPTED)
async def post_document_pipeline(document_id: str, db: Session = Depends(get_db)) -> dict:
    job, _created = trigger_document_pipeline(db, document_id)
    return {
        "success": True,
        "code": "OK",
        "message": "Document pipeline queued.",
        "data": pipeline_job_payload(job).model_dump(mode="json"),
    }


@router.get("/documents/{document_id}/pipeline")
async def get_document_pipeline(document_id: str, db: Session = Depends(get_db)) -> dict:
    job = get_latest_pipeline_job(db, document_id)
    return {
        "success": True,
        "code": "OK",
        "message": "Pipeline job loaded.",
        "data": pipeline_job_payload(job).model_dump(mode="json"),
    }


@router.get("/pipeline/jobs")
async def get_pipeline_jobs(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    payload = list_pipeline_jobs(db, limit=limit, offset=offset, status_filter=status)
    return {
        "success": True,
        "code": "OK",
        "message": "Pipeline jobs loaded.",
        "data": payload.model_dump(mode="json"),
    }


@router.get("/pipeline/jobs/{job_id}")
async def get_pipeline_job_api(job_id: str, db: Session = Depends(get_db)) -> dict:
    payload = PipelineJobOut.model_validate(pipeline_job_payload(get_pipeline_job(db, job_id)))
    return {
        "success": True,
        "code": "OK",
        "message": "Pipeline job loaded.",
        "data": payload.model_dump(mode="json"),
    }


@router.get("/pipeline/jobs/{job_id}/events")
async def get_pipeline_job_events_api(job_id: str, db: Session = Depends(get_db)) -> dict:
    payload = PipelineJobEventsOut.model_validate(get_pipeline_job_events(db, job_id))
    return {
        "success": True,
        "code": "OK",
        "message": "Pipeline job events loaded.",
        "data": payload.model_dump(mode="json"),
    }


@router.get("/pipeline/status")
async def get_pipeline_status_api(db: Session = Depends(get_db)) -> dict:
    payload = PipelineStatusOut.model_validate(get_pipeline_status(db))
    return {
        "success": True,
        "code": "OK",
        "message": "Pipeline status loaded.",
        "data": payload.model_dump(mode="json"),
    }


@router.get("/pipeline/events/stream")
async def stream_pipeline_events_api(since_event_id: str | None = None) -> StreamingResponse:
    return StreamingResponse(
        stream_pipeline_events(since_event_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/pipeline/jobs/{job_id}/priority")
async def post_pipeline_job_priority(job_id: str, payload: PipelinePriorityUpdate, db: Session = Depends(get_db)) -> dict:
    job = update_pipeline_priority(db, job_id, payload.priority)
    return {
        "success": True,
        "code": "OK",
        "message": "Pipeline job priority updated.",
        "data": pipeline_job_payload(job).model_dump(mode="json"),
    }


@router.post("/pipeline/jobs/{job_id}/cancel")
async def post_pipeline_job_cancel(job_id: str, db: Session = Depends(get_db)) -> dict:
    job = cancel_pipeline_job(db, job_id)
    return {
        "success": True,
        "code": "OK",
        "message": "Pipeline job cancel requested.",
        "data": pipeline_job_payload(job).model_dump(mode="json"),
    }


@router.post("/pipeline/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def post_pipeline_job_retry(job_id: str, db: Session = Depends(get_db)) -> dict:
    job = retry_pipeline_job(db, job_id)
    return {
        "success": True,
        "code": "OK",
        "message": "Pipeline job retry queued.",
        "data": pipeline_job_payload(job).model_dump(mode="json"),
    }


@router.post("/pipeline/batch/process-missing", status_code=status.HTTP_202_ACCEPTED)
async def post_pipeline_batch_process_missing(project_id: str | None = None, db: Session = Depends(get_db)) -> dict:
    payload = PipelineBatchOut.model_validate(batch_process_missing_documents(db, project_id=project_id))
    return {
        "success": True,
        "code": "OK",
        "message": "Missing document pipelines queued.",
        "data": payload.model_dump(mode="json"),
    }


@router.post("/pipeline/batch/cancel")
async def post_pipeline_batch_cancel(payload: PipelineBatchActionRequest, db: Session = Depends(get_db)) -> dict:
    result = batch_cancel_pipeline_jobs(
        db,
        job_ids=payload.job_ids,
        status_filter=payload.status,
        project_id=payload.project_id,
    )
    response = PipelineBatchActionOut.model_validate(result)
    return {
        "success": True,
        "code": "OK",
        "message": "Pipeline jobs canceled.",
        "data": response.model_dump(mode="json"),
    }


@router.post("/pipeline/batch/retry", status_code=status.HTTP_202_ACCEPTED)
async def post_pipeline_batch_retry(payload: PipelineBatchActionRequest, db: Session = Depends(get_db)) -> dict:
    result = batch_retry_pipeline_jobs(
        db,
        job_ids=payload.job_ids,
        status_filter=payload.status,
        project_id=payload.project_id,
    )
    response = PipelineBatchActionOut.model_validate(result)
    return {
        "success": True,
        "code": "OK",
        "message": "Pipeline jobs retried.",
        "data": response.model_dump(mode="json"),
    }


@router.post("/documents/{document_id}/pipeline/reprocess", status_code=status.HTTP_202_ACCEPTED)
async def post_document_pipeline_reprocess(document_id: str, db: Session = Depends(get_db)) -> dict:
    job, _created = reprocess_document_pipeline(db, document_id)
    return {
        "success": True,
        "code": "OK",
        "message": "Document pipeline reprocess queued.",
        "data": pipeline_job_payload(job).model_dump(mode="json"),
    }


@router.get("/providers/status")
async def get_providers_status_api() -> dict:
    payload = ProvidersStatusOut.model_validate(get_providers_status())
    return {
        "success": True,
        "code": "OK",
        "message": "Provider status loaded.",
        "data": payload.model_dump(mode="json"),
    }


@router.post("/providers/embedding/test")
async def post_embedding_provider_test(db: Session = Depends(get_db)) -> dict:
    try:
        diagnostic = test_embedding_provider()
        record_provider_diagnostic_success(db, provider_kind="embedding", diagnostic=diagnostic)
    except Exception as error:
        try:
            record_embedding_provider_failure(db, error)
        except Exception:
            pass
        raise
    payload = ProviderDiagnosticOut(**diagnostic.__dict__)
    return {
        "success": True,
        "code": "OK",
        "message": "Embedding provider tested.",
        "data": payload.model_dump(mode="json"),
    }


@router.post("/providers/llm/test")
async def post_llm_provider_test(db: Session = Depends(get_db)) -> dict:
    try:
        diagnostic = test_llm_provider()
        record_provider_diagnostic_success(db, provider_kind="llm", diagnostic=diagnostic)
    except Exception as error:
        try:
            record_llm_provider_failure(db, error)
        except Exception:
            pass
        raise
    payload = ProviderDiagnosticOut(**diagnostic.__dict__)
    return {
        "success": True,
        "code": "OK",
        "message": "LLM provider tested.",
        "data": payload.model_dump(mode="json"),
    }


@router.get("/providers/diagnostics/history")
async def get_provider_diagnostics_history_api(
    provider_kind: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    db: Session = Depends(get_db),
) -> dict:
    payload = ProviderDiagnosticHistoryOut.model_validate(
        get_provider_diagnostic_history(db, provider_kind=provider_kind, limit=limit)
    )
    return {
        "success": True,
        "code": "OK",
        "message": "Provider diagnostic history loaded.",
        "data": payload.model_dump(mode="json"),
    }


@router.patch("/documents/{document_id}/status")
async def patch_document_status(document_id: str, payload: DocumentStatusUpdate, db: Session = Depends(get_db)) -> dict:
    document = update_document_status(db, document_id, payload.status)
    return {
        "success": True,
        "code": "OK",
        "message": "Document updated.",
        "data": _document_payload(db, document),
    }


@router.delete("/documents/{document_id}")
async def hard_delete_document(document_id: str, db: Session = Depends(get_db)) -> dict:
    deleted_id = delete_document(db, document_id)
    return {
        "success": True,
        "code": "OK",
        "message": "Document deleted.",
        "data": {
            "id": deleted_id,
        },
    }


@router.post("/documents/{document_id}/parse")
async def post_document_parse(document_id: str, db: Session = Depends(get_db)) -> dict:
    result = parse_document(db, document_id)
    return {
        "success": True,
        "code": "OK",
        "message": "Document parsed.",
        "data": ParseResultOut.model_validate(result).model_dump(mode="json"),
    }


@router.get("/documents/{document_id}/parse")
async def get_document_parse(document_id: str, db: Session = Depends(get_db)) -> dict:
    result = get_parse_result(db, document_id)
    return {
        "success": True,
        "code": "OK",
        "message": "Parse result loaded.",
        "data": ParseResultOut.model_validate(result).model_dump(mode="json"),
    }


@router.post("/documents/{document_id}/chunks")
async def post_document_chunks(document_id: str, db: Session = Depends(get_db)) -> dict:
    result = chunk_document(db, document_id)
    return {
        "success": True,
        "code": "OK",
        "message": "Document chunked.",
        "data": ChunkResultOut.model_validate(result).model_dump(mode="json"),
    }


@router.get("/documents/{document_id}/chunks")
async def get_document_chunk_details(document_id: str, db: Session = Depends(get_db)) -> dict:
    result, chunks = get_document_chunks(db, document_id)
    payload = DocumentChunksOut(
        document_id=document_id,
        chunk_result=ChunkResultOut.model_validate(result),
        chunks=[ChunkMetaOut.model_validate(chunk) for chunk in chunks],
    )
    return {
        "success": True,
        "code": "OK",
        "message": "Document chunks loaded.",
        "data": payload.model_dump(mode="json"),
    }


@router.get("/chunks")
async def get_chunks(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    document_id: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    items, total = list_chunks(db, document_id=document_id, limit=limit, offset=offset)
    payload = ChunkListOut(
        items=[ChunkMetaOut.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )
    return {
        "success": True,
        "code": "OK",
        "message": "Chunks loaded.",
        "data": payload.model_dump(mode="json"),
    }


@router.get("/chunks/{chunk_id}")
async def get_chunk(chunk_id: str, db: Session = Depends(get_db)) -> dict:
    chunk = get_chunk_content(db, chunk_id)
    return {
        "success": True,
        "code": "OK",
        "message": "Chunk content loaded.",
        "data": ChunkContentOut.model_validate(chunk).model_dump(mode="json"),
    }


@router.post("/documents/{document_id}/index")
async def post_document_index(document_id: str, db: Session = Depends(get_db)) -> dict:
    result = index_document(db, document_id)
    return {
        "success": True,
        "code": "OK",
        "message": "Document indexed.",
        "data": EmbeddingResultOut.model_validate(result).model_dump(mode="json"),
    }


@router.get("/documents/{document_id}/index")
async def get_document_index(document_id: str, db: Session = Depends(get_db)) -> dict:
    result = get_index_result(db, document_id)
    return {
        "success": True,
        "code": "OK",
        "message": "Index result loaded.",
        "data": EmbeddingResultOut.model_validate(result).model_dump(mode="json"),
    }


@router.get("/index/status")
async def get_index_status_api(db: Session = Depends(get_db)) -> dict:
    payload = IndexStatusOut(**get_index_status(db))
    return {
        "success": True,
        "code": "OK",
        "message": "Index status loaded.",
        "data": payload.model_dump(mode="json"),
    }


@router.get("/index/diagnostics")
async def get_index_diagnostics_api(db: Session = Depends(get_db)) -> dict:
    payload = IndexDiagnosticsOut(**get_index_diagnostics(db))
    return {
        "success": True,
        "code": "OK",
        "message": "Index diagnostics loaded.",
        "data": payload.model_dump(mode="json"),
    }


@router.get("/index/collections")
async def get_index_collections_api(db: Session = Depends(get_db)) -> dict:
    payload = IndexCollectionsOut.model_validate(list_index_collections(db))
    return {
        "success": True,
        "code": "OK",
        "message": "Index collections loaded.",
        "data": payload.model_dump(mode="json"),
    }


@router.post("/index/maintenance/reset")
async def post_index_maintenance_reset(payload: IndexResetRequest, db: Session = Depends(get_db)) -> dict:
    result = reset_current_index(
        db,
        confirm=payload.confirm,
        collection_name=payload.collection_name,
        clear_embedding_results=payload.clear_embedding_results,
    )
    response = IndexResetOut(**result)
    return {
        "success": True,
        "code": "OK",
        "message": "Index reset completed.",
        "data": response.model_dump(mode="json"),
    }
