import { postJson } from "./client";
import type { ApiResponse, RetrievalSearchResult } from "../types/api";

export interface RetrievalSearchPayload {
  query: string;
  top_k?: number;
  project_id?: string | null;
  document_id?: string | null;
}

export function searchRetrieval(payload: RetrievalSearchPayload) {
  return postJson<ApiResponse<RetrievalSearchResult>>("/api/retrieval/search", payload);
}
