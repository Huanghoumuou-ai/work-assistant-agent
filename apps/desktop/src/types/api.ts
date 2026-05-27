export interface ApiResponse<T> {
  success: boolean;
  code: string;
  message: string;
  data: T;
}

export interface HealthStatus {
  app_name: string;
  version: string;
  environment: string;
  database: {
    ok: boolean;
  };
  timestamp: string;
}

export interface SettingsStatus {
  app: {
    name: string;
    environment: string;
    version: string;
    timezone: string;
  };
  backend: {
    host: string;
    port: number;
  };
  paths: {
    data_dir: string;
    files_dir: string;
    parsed_dir: string;
    sqlite_db_path: string;
    chroma_persist_dir: string;
  };
  database: {
    type: string;
    ok: boolean;
    migration: {
      current_revision: string | null;
      head_revision: string;
      up_to_date: boolean;
    };
  };
  pipeline_worker: {
    running: boolean;
    worker_id: string | null;
    concurrency: number;
    poll_interval_seconds: number;
    lock_timeout_seconds: number;
  };
  providers: {
    openai_configured: boolean;
    openai_base_url_configured: boolean;
    openai_model: string;
    llm_provider: string;
    embedding_provider: string;
    embedding_model: string;
    chroma_collection_name: string;
  };
  limits: {
    max_upload_size_mb: number;
    max_parse_chars: number;
    max_parse_pages: number;
    max_parse_rows: number;
    max_parse_sheets: number;
    max_chunk_chars: number;
    chunk_overlap_chars: number;
    max_chunks_per_document: number;
    embedding_batch_size: number;
    embedding_timeout_seconds: number;
    default_retrieval_top_k: number;
    max_retrieval_top_k: number;
    llm_timeout_seconds: number;
    rag_top_k: number;
    rag_max_context_chars: number;
    rag_source_excerpt_chars: number;
    rag_query_rewrite_enabled: boolean;
    rag_query_rewrite_max_chars: number;
    memory_context_max_chars_per_item: number;
    memory_context_max_total_chars: number;
    chat_context_recent_messages: number;
    chat_context_max_chars: number;
    conversation_summary_max_messages: number;
    conversation_summary_max_chars: number;
    conversation_summary_target_chars: number;
    auto_summary_enabled: boolean;
    auto_summary_min_new_messages: number;
    auto_summary_min_total_messages: number;
    auto_summary_max_per_chat: number;
  };
}

export type DocumentStatus = "uploaded" | "archived";
export type ParseStatus = "parsed" | "failed";
export type ChunkStatus = "chunked" | "failed";
export type EmbeddingStatus = "indexed" | "failed";

export interface ParseResult {
  document_id: string;
  status: ParseStatus;
  source_sha256: string;
  parsed_relative_path: string | null;
  parser_name: string | null;
  parser_version: string | null;
  content_sha256: string | null;
  char_count: number;
  truncated: boolean;
  error_message: string | null;
  parsed_at: string;
}

export interface ChunkResult {
  document_id: string;
  status: ChunkStatus;
  parse_content_sha256: string;
  cleaner_name: string | null;
  cleaner_version: string | null;
  chunker_name: string | null;
  chunker_version: string | null;
  chunk_count: number;
  max_chunk_chars: number;
  overlap_chars: number;
  truncated: boolean;
  error_message: string | null;
  chunked_at: string;
  created_at: string;
  updated_at: string;
}

export interface ChunkMeta {
  id: string;
  document_id: string;
  chunk_index: number;
  content_sha256: string;
  char_start: number;
  char_end: number;
  char_count: number;
  metadata_json: string;
  created_at: string;
}

export interface ChunkContent extends ChunkMeta {
  content: string;
}

export interface EmbeddingResult {
  document_id: string;
  status: EmbeddingStatus;
  provider: string;
  model: string;
  embedding_dimension: number;
  chunk_set_sha256: string;
  indexed_chunk_count: number;
  vector_collection: string;
  vector_ids_json: string | null;
  error_message: string | null;
  indexed_at: string;
  created_at: string;
  updated_at: string;
}

export interface IndexStatus {
  provider_configured: boolean;
  collection_name: string;
  persist_path: string;
  indexed_document_count: number;
  vector_count: number;
}

export interface ProviderDiagnostic {
  provider: string;
  model: string;
  configured: boolean;
  ok: boolean;
  latency_ms: number;
  message: string;
  dimension: number | null;
  response_preview: string | null;
}

export interface IndexProviderModelCount {
  provider: string;
  model: string;
  status: string;
  count: number;
}

export interface IndexFailure {
  document_id: string;
  provider: string;
  model: string;
  error_message: string | null;
  updated_at: string;
}

export interface IndexDiagnostics {
  status: "ok" | "warning";
  collection_name: string;
  persist_path: string;
  vector_count: number;
  collection_dimension: number | null;
  indexed_document_count: number;
  db_embedding_dimensions: number[];
  provider_model_counts: IndexProviderModelCount[];
  recent_failures: IndexFailure[];
  warning: string | null;
}

export interface IndexResetResult {
  collection_name: string;
  vectors_deleted: boolean;
  embedding_results_deleted: number;
}

export interface IndexCollection {
  name: string;
  vector_count: number;
  dimension: number | null;
  indexed_document_count: number;
  is_current: boolean;
}

export interface IndexCollections {
  items: IndexCollection[];
  total: number;
}

export type PipelineJobStatus = "queued" | "running" | "succeeded" | "failed" | "canceled";

export interface PipelineJob {
  id: string;
  document_id: string;
  status: PipelineJobStatus;
  current_step: "parse" | "chunk" | "index" | null;
  steps: string[];
  step_results: Record<string, unknown>;
  cancel_requested: boolean;
  progress_percent: number;
  priority: number;
  attempt_count: number;
  max_attempts: number;
  next_run_at: string;
  locked_by: string | null;
  lock_expires_at: string | null;
  heartbeat_at: string | null;
  last_error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
}

export interface PipelineJobEvent {
  id: string;
  job_id: string;
  document_id: string;
  event_type: string;
  step: string | null;
  message: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface PipelineJobEvents {
  items: PipelineJobEvent[];
  total: number;
}

export interface PipelineJobList {
  items: PipelineJob[];
  total: number;
  limit: number;
  offset: number;
}

export interface PipelineBatch {
  items: PipelineJob[];
  total: number;
}

export interface PipelineBatchAction {
  items: PipelineJob[];
  total: number;
  acted: number;
  skipped: number;
}

export interface PipelineBatchActionRequest {
  job_ids?: string[];
  status?: "queued" | "running" | "failed" | "canceled";
  project_id?: string | null;
}

export interface PipelineStatus {
  queued_count: number;
  running_count: number;
  succeeded_count: number;
  failed_count: number;
  canceled_count: number;
  active_count: number;
  recent_failures: PipelineJob[];
  provider_configured: boolean;
  worker_running: boolean;
  worker_id: string | null;
  worker_concurrency: number;
  stale_running_count: number;
  oldest_queued_at: string | null;
}

export interface ProviderCheck {
  provider: string;
  model: string;
  configured: boolean;
  reason: string | null;
}

export interface ProvidersStatus {
  llm: ProviderCheck;
  embedding: ProviderCheck;
  openai_base_url_configured: boolean;
  chroma_collection_name: string;
}

export interface ProviderDiagnosticRun {
  id: string;
  provider_kind: "embedding" | "llm";
  provider: string;
  model: string;
  configured: boolean;
  ok: boolean;
  latency_ms: number;
  message: string;
  dimension: number | null;
  response_preview: string | null;
  error_message: string | null;
  created_at: string;
}

export interface ProviderDiagnosticHistory {
  items: ProviderDiagnosticRun[];
  total: number;
}

export interface DocumentItem {
  id: string;
  project_id: string | null;
  original_filename: string;
  stored_filename: string;
  relative_path: string;
  extension: string;
  mime_type: string | null;
  size_bytes: number;
  sha256: string;
  status: DocumentStatus;
  created_at: string;
  updated_at: string;
  parse_result: ParseResult | null;
  chunk_result: ChunkResult | null;
  embedding_result: EmbeddingResult | null;
}

export interface DocumentList {
  items: DocumentItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface ProjectItem {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface RetrievalHit {
  rank: number;
  document_id: string;
  chunk_id: string;
  chunk_index: number;
  score: number;
  distance: number;
  source_filename: string;
  project_id: string | null;
  char_start: number;
  char_end: number;
  content_sha256: string;
  parse_content_sha256: string;
  chunk_set_sha256: string;
  provider: string;
  model: string;
}

export interface RetrievalSearchResult {
  query: string;
  top_k: number;
  items: RetrievalHit[];
}

export interface RagSource {
  source_id: string;
  rank: number;
  document_id: string;
  chunk_id: string;
  chunk_index: number;
  source_filename: string;
  project_id: string | null;
  uploaded_at: string;
  char_start: number;
  char_end: number;
  score: number;
  distance: number;
  excerpt: string;
}

export interface RagSearchResult {
  answer: string;
  sources: RagSource[];
  memory_sources: MemorySource[];
  model: string;
  provider: string;
  query_used: string | null;
  query_rewritten: boolean;
  usage: Record<string, unknown> | null;
}

export interface ConversationItem {
  id: string;
  title: string;
  project_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConversationList {
  items: ConversationItem[];
  total: number;
  limit: number;
  offset: number;
}

export type MessageRole = "user" | "assistant";

export interface ChatMessage {
  id: string;
  conversation_id: string;
  role: MessageRole;
  content: string;
  sources: RagSource[];
  memory_sources: MemorySource[];
  provider: string | null;
  model: string | null;
  created_at: string;
}

export interface ConversationMessages {
  conversation: ConversationItem;
  messages: ChatMessage[];
}

export interface ConversationSummary {
  conversation_id: string;
  status: "missing" | "summarized" | "failed";
  summary: string | null;
  message_count: number;
  last_message_id: string | null;
  provider: string | null;
  model: string | null;
  error_message: string | null;
  generated_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  stale: boolean;
  new_message_count: number;
  needs_refresh: boolean;
}

export interface ChatResponse {
  conversation: ConversationItem;
  user_message: ChatMessage;
  assistant_message: ChatMessage;
  summary: ConversationSummary | null;
}

export type MemoryType = "note" | "requirement" | "decision" | "rule";
export type MemoryStatus = "active" | "archived";
export type MemoryStatusFilter = MemoryStatus | "all";

export interface MemoryItem {
  id: string;
  project_id: string | null;
  project_name: string | null;
  type: MemoryType;
  title: string;
  content: string;
  status: MemoryStatus;
  source_type: string;
  source_ref: string | null;
  occurred_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MemoryList {
  items: MemoryItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface MemorySearchItem {
  rank: number;
  score: number;
  matched_fields: string[];
  memory: MemoryItem;
}

export interface MemorySearchResult {
  query: string;
  items: MemorySearchItem[];
}

export type MemorySuggestionStatus = "pending" | "accepted" | "rejected";

export interface MemorySuggestion {
  id: string;
  conversation_id: string | null;
  project_id: string | null;
  project_name: string | null;
  type: MemoryType;
  title: string;
  content: string;
  rationale: string | null;
  status: MemorySuggestionStatus;
  source_type: string;
  source_ref: string | null;
  memory_id: string | null;
  created_at: string;
  reviewed_at: string | null;
  updated_at: string;
}

export interface MemorySuggestionList {
  items: MemorySuggestion[];
  total: number;
  limit: number;
  offset: number;
}

export interface MemorySuggestionBatch {
  items: MemorySuggestion[];
  total: number;
}

export interface MemorySuggestionAcceptResult {
  suggestion: MemorySuggestion;
  memory: MemoryItem;
}

export interface MemorySource {
  source_id: string;
  rank: number;
  memory_id: string;
  project_id: string | null;
  project_name: string | null;
  type: MemoryType;
  title: string;
  content: string;
  occurred_at: string | null;
  score: number;
}
