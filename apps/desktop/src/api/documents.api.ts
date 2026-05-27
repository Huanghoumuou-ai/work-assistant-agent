import { backendUrl, deleteJson, getJson, patchJson, postForm, postJson } from "./client";
import type {
  ApiResponse,
  ChunkContent,
  ChunkResult,
  DocumentItem,
  DocumentList,
  DocumentStatus,
  EmbeddingResult,
  ParseResult,
  PipelineBatch,
  PipelineBatchAction,
  PipelineBatchActionRequest,
  PipelineJobEvents,
  PipelineJob,
  PipelineJobList,
  PipelineJobStatus,
  PipelineStatus,
  ProvidersStatus,
} from "../types/api";

export interface DocumentQuery {
  limit: number;
  offset: number;
  projectId?: string;
  status?: DocumentStatus;
}

export function getDocuments(query: DocumentQuery) {
  const params = new URLSearchParams({
    limit: String(query.limit),
    offset: String(query.offset),
  });
  if (query.projectId) {
    params.set("project_id", query.projectId);
  }
  if (query.status) {
    params.set("status", query.status);
  }
  return getJson<ApiResponse<DocumentList>>(`/api/documents?${params.toString()}`);
}

export function uploadDocument(file: File, projectId?: string) {
  const formData = new FormData();
  formData.append("file", file);
  if (projectId) {
    formData.append("project_id", projectId);
  }
  return postForm<ApiResponse<DocumentItem>>("/api/upload", formData);
}

export function createTextDocument(payload: { title?: string | null; content: string; project_id?: string | null }) {
  return postJson<ApiResponse<DocumentItem>>("/api/documents/text", payload);
}

export function updateDocumentStatus(documentId: string, status: DocumentStatus) {
  return patchJson<ApiResponse<DocumentItem>>(`/api/documents/${documentId}/status`, { status });
}

export function deleteDocument(documentId: string) {
  return deleteJson<ApiResponse<{ id: string }>>(`/api/documents/${documentId}`);
}

export function parseDocument(documentId: string) {
  return postJson<ApiResponse<ParseResult>>(`/api/documents/${documentId}/parse`, {});
}

export function chunkDocument(documentId: string) {
  return postJson<ApiResponse<ChunkResult>>(`/api/documents/${documentId}/chunks`, {});
}

export function getChunkContent(chunkId: string) {
  return getJson<ApiResponse<ChunkContent>>(`/api/chunks/${chunkId}`);
}

export function indexDocument(documentId: string) {
  return postJson<ApiResponse<EmbeddingResult>>(`/api/documents/${documentId}/index`, {});
}

export function triggerDocumentPipeline(documentId: string) {
  return postJson<ApiResponse<PipelineJob>>(`/api/documents/${documentId}/pipeline`, {});
}

export function getDocumentPipeline(documentId: string) {
  return getJson<ApiResponse<PipelineJob>>(`/api/documents/${documentId}/pipeline`);
}

export function getPipelineJobs(query: { limit?: number; offset?: number; status?: PipelineJobStatus } = {}) {
  const params = new URLSearchParams({
    limit: String(query.limit ?? 50),
    offset: String(query.offset ?? 0),
  });
  if (query.status) {
    params.set("status", query.status);
  }
  return getJson<ApiResponse<PipelineJobList>>(`/api/pipeline/jobs?${params.toString()}`);
}

export function getPipelineJob(jobId: string) {
  return getJson<ApiResponse<PipelineJob>>(`/api/pipeline/jobs/${jobId}`);
}

export function getPipelineJobEvents(jobId: string) {
  return getJson<ApiResponse<PipelineJobEvents>>(`/api/pipeline/jobs/${jobId}/events`);
}

export function getPipelineStatus() {
  return getJson<ApiResponse<PipelineStatus>>("/api/pipeline/status");
}

export function cancelPipelineJob(jobId: string) {
  return postJson<ApiResponse<PipelineJob>>(`/api/pipeline/jobs/${jobId}/cancel`, {});
}

export function retryPipelineJob(jobId: string) {
  return postJson<ApiResponse<PipelineJob>>(`/api/pipeline/jobs/${jobId}/retry`, {});
}

export function updatePipelineJobPriority(jobId: string, priority: number) {
  return postJson<ApiResponse<PipelineJob>>(`/api/pipeline/jobs/${jobId}/priority`, { priority });
}

export function reprocessDocumentPipeline(documentId: string) {
  return postJson<ApiResponse<PipelineJob>>(`/api/documents/${documentId}/pipeline/reprocess`, {});
}

export function processMissingDocuments(projectId?: string) {
  const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  return postJson<ApiResponse<PipelineBatch>>(`/api/pipeline/batch/process-missing${query}`, {});
}

export function batchCancelPipelineJobs(payload: PipelineBatchActionRequest) {
  return postJson<ApiResponse<PipelineBatchAction>>("/api/pipeline/batch/cancel", payload);
}

export function batchRetryPipelineJobs(payload: PipelineBatchActionRequest) {
  return postJson<ApiResponse<PipelineBatchAction>>("/api/pipeline/batch/retry", payload);
}

export function pipelineEventsStreamUrl(sinceEventId?: string) {
  const params = new URLSearchParams();
  if (sinceEventId) {
    params.set("since_event_id", sinceEventId);
  }
  const query = params.toString();
  return `${backendUrl}/api/pipeline/events/stream${query ? `?${query}` : ""}`;
}

export function getProvidersStatus() {
  return getJson<ApiResponse<ProvidersStatus>>("/api/providers/status");
}
