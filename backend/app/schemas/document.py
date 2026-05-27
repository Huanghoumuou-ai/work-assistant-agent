from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ParseResultOut(BaseModel):
    document_id: str
    status: str
    source_sha256: str
    parsed_relative_path: str | None
    parser_name: str | None
    parser_version: str | None
    content_sha256: str | None
    char_count: int
    truncated: bool
    error_message: str | None
    parsed_at: datetime

    model_config = {"from_attributes": True}


class ChunkResultOut(BaseModel):
    document_id: str
    status: str
    parse_content_sha256: str
    cleaner_name: str | None
    cleaner_version: str | None
    chunker_name: str | None
    chunker_version: str | None
    chunk_count: int
    max_chunk_chars: int
    overlap_chars: int
    truncated: bool
    error_message: str | None
    chunked_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EmbeddingResultOut(BaseModel):
    document_id: str
    status: str
    provider: str
    model: str
    embedding_dimension: int
    chunk_set_sha256: str
    indexed_chunk_count: int
    vector_collection: str
    vector_ids_json: str | None
    error_message: str | None
    indexed_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class IndexStatusOut(BaseModel):
    provider_configured: bool
    collection_name: str
    persist_path: str
    indexed_document_count: int
    vector_count: int


class ProviderDiagnosticOut(BaseModel):
    provider: str
    model: str
    configured: bool
    ok: bool
    latency_ms: int
    message: str
    dimension: int | None = None
    response_preview: str | None = None


class IndexProviderModelCountOut(BaseModel):
    provider: str
    model: str
    status: str
    count: int


class IndexFailureOut(BaseModel):
    document_id: str
    provider: str
    model: str
    error_message: str | None
    updated_at: datetime


class IndexDiagnosticsOut(BaseModel):
    status: str
    collection_name: str
    persist_path: str
    vector_count: int
    collection_dimension: int | None
    indexed_document_count: int
    db_embedding_dimensions: list[int]
    provider_model_counts: list[IndexProviderModelCountOut]
    recent_failures: list[IndexFailureOut]
    warning: str | None = None


class IndexResetOut(BaseModel):
    collection_name: str
    vectors_deleted: bool
    embedding_results_deleted: int


class IndexCollectionOut(BaseModel):
    name: str
    vector_count: int
    dimension: int | None
    indexed_document_count: int
    is_current: bool


class IndexCollectionsOut(BaseModel):
    items: list[IndexCollectionOut]
    total: int


class PipelineJobOut(BaseModel):
    id: str
    document_id: str
    status: str
    current_step: str | None
    steps: list[str]
    step_results: dict
    cancel_requested: bool
    progress_percent: int
    priority: int
    attempt_count: int
    max_attempts: int
    next_run_at: datetime
    locked_by: str | None
    lock_expires_at: datetime | None
    heartbeat_at: datetime | None
    last_error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class PipelineJobEventOut(BaseModel):
    id: str
    job_id: str
    document_id: str
    event_type: str
    step: str | None
    message: str | None
    payload: dict
    created_at: datetime


class PipelineJobEventsOut(BaseModel):
    items: list[PipelineJobEventOut]
    total: int


class PipelineJobListOut(BaseModel):
    items: list[PipelineJobOut]
    total: int
    limit: int
    offset: int


class PipelineStatusOut(BaseModel):
    queued_count: int
    running_count: int
    succeeded_count: int
    failed_count: int
    canceled_count: int
    active_count: int
    recent_failures: list[PipelineJobOut]
    provider_configured: bool
    worker_running: bool
    worker_id: str | None
    worker_concurrency: int
    stale_running_count: int
    oldest_queued_at: datetime | None


class PipelineBatchOut(BaseModel):
    items: list[PipelineJobOut]
    total: int


class PipelineBatchActionOut(BaseModel):
    items: list[PipelineJobOut]
    total: int
    acted: int
    skipped: int


class ProviderCheckOut(BaseModel):
    provider: str
    model: str
    configured: bool
    reason: str | None = None


class ProvidersStatusOut(BaseModel):
    llm: ProviderCheckOut
    embedding: ProviderCheckOut
    openai_base_url_configured: bool
    chroma_collection_name: str


class ProviderDiagnosticRunOut(BaseModel):
    id: str
    provider_kind: str
    provider: str
    model: str
    configured: bool
    ok: bool
    latency_ms: int
    message: str
    dimension: int | None
    response_preview: str | None
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ProviderDiagnosticHistoryOut(BaseModel):
    items: list[ProviderDiagnosticRunOut]
    total: int


class ChunkMetaOut(BaseModel):
    id: str
    document_id: str
    chunk_index: int
    content_sha256: str
    char_start: int
    char_end: int
    char_count: int
    metadata_json: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ChunkContentOut(ChunkMetaOut):
    content: str


class ChunkListOut(BaseModel):
    items: list[ChunkMetaOut]
    total: int
    limit: int
    offset: int


class DocumentChunksOut(BaseModel):
    document_id: str
    chunk_result: ChunkResultOut
    chunks: list[ChunkMetaOut]


class DocumentOut(BaseModel):
    id: str
    project_id: str | None
    original_filename: str
    stored_filename: str
    relative_path: str
    extension: str
    mime_type: str | None
    size_bytes: int
    sha256: str
    status: str
    created_at: datetime
    updated_at: datetime
    parse_result: ParseResultOut | None = None
    chunk_result: ChunkResultOut | None = None
    embedding_result: EmbeddingResultOut | None = None

    model_config = {"from_attributes": True}


class DocumentListOut(BaseModel):
    items: list[DocumentOut]
    total: int
    limit: int
    offset: int
