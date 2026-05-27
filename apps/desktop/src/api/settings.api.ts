import { getJson, postJson } from "./client";
import type {
  ApiResponse,
  HealthStatus,
  IndexCollections,
  IndexDiagnostics,
  IndexResetResult,
  IndexStatus,
  ProviderDiagnostic,
  ProviderDiagnosticHistory,
  ProvidersStatus,
  SettingsStatus,
} from "../types/api";

export function getHealth() {
  return getJson<ApiResponse<HealthStatus>>("/health");
}

export function getSettingsStatus() {
  return getJson<ApiResponse<SettingsStatus>>("/api/settings/status");
}

export function getIndexStatus() {
  return getJson<ApiResponse<IndexStatus>>("/api/index/status");
}

export function getProvidersStatus() {
  return getJson<ApiResponse<ProvidersStatus>>("/api/providers/status");
}

export function testEmbeddingProvider() {
  return postJson<ApiResponse<ProviderDiagnostic>>("/api/providers/embedding/test", {});
}

export function testLlmProvider() {
  return postJson<ApiResponse<ProviderDiagnostic>>("/api/providers/llm/test", {});
}

export function getIndexDiagnostics() {
  return getJson<ApiResponse<IndexDiagnostics>>("/api/index/diagnostics");
}

export function getIndexCollections() {
  return getJson<ApiResponse<IndexCollections>>("/api/index/collections");
}

export function resetIndexMaintenance(payload: { confirm: "RESET_INDEX"; collection_name: string; clear_embedding_results: boolean }) {
  return postJson<ApiResponse<IndexResetResult>>("/api/index/maintenance/reset", payload);
}

export function getProviderDiagnosticHistory(providerKind?: "embedding" | "llm", limit = 20) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (providerKind) {
    params.set("provider_kind", providerKind);
  }
  return getJson<ApiResponse<ProviderDiagnosticHistory>>(`/api/providers/diagnostics/history?${params.toString()}`);
}
