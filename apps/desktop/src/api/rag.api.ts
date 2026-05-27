import { postJson } from "./client";
import type { ApiResponse, RagSearchResult } from "../types/api";

export interface RagSearchPayload {
  query: string;
  top_k?: number;
  project_id?: string | null;
  document_id?: string | null;
  include_memory?: boolean;
  memory_limit?: number;
}

export function searchRag(payload: RagSearchPayload) {
  return postJson<ApiResponse<RagSearchResult>>("/api/rag/search", payload);
}
