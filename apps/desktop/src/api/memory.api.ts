import { getJson, patchJson, postJson } from "./client";
import type { ApiResponse, MemoryItem, MemoryList, MemorySearchResult, MemoryStatus, MemoryStatusFilter, MemoryType } from "../types/api";

export interface MemoryQuery {
  limit: number;
  offset: number;
  projectId?: string;
  type?: MemoryType | "";
  status?: MemoryStatusFilter;
}

export interface MemoryPayload {
  project_id?: string | null;
  type: MemoryType;
  title: string;
  content: string;
  occurred_at?: string | null;
}

export interface MemorySearchPayload {
  query: string;
  limit?: number;
  project_id?: string | null;
  types?: MemoryType[];
  include_archived?: boolean;
}

export function getMemories(query: MemoryQuery) {
  const params = new URLSearchParams({
    limit: String(query.limit),
    offset: String(query.offset),
  });
  if (query.projectId) {
    params.set("project_id", query.projectId);
  }
  if (query.type) {
    params.set("type", query.type);
  }
  if (query.status) {
    params.set("status", query.status);
  }
  return getJson<ApiResponse<MemoryList>>(`/api/memory?${params.toString()}`);
}

export function createMemory(payload: MemoryPayload) {
  return postJson<ApiResponse<MemoryItem>>("/api/memory", payload);
}

export function updateMemory(memoryId: string, payload: Partial<MemoryPayload>) {
  return patchJson<ApiResponse<MemoryItem>>(`/api/memory/${memoryId}`, payload);
}

export function updateMemoryStatus(memoryId: string, status: MemoryStatus) {
  return patchJson<ApiResponse<MemoryItem>>(`/api/memory/${memoryId}/status`, { status });
}

export function searchMemories(payload: MemorySearchPayload) {
  return postJson<ApiResponse<MemorySearchResult>>("/api/memory/search", payload);
}

export function getMemory(memoryId: string) {
  return getJson<ApiResponse<MemoryItem>>(`/api/memory/${memoryId}`);
}
