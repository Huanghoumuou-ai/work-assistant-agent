import { useEffect, useState } from "react";
import { AlertTriangle, Activity, RefreshCw, RotateCcw, Trash2, Zap } from "lucide-react";

import { backendUrl } from "../api/client";
import {
  getHealth,
  getIndexCollections,
  getIndexDiagnostics,
  getIndexStatus,
  getProviderDiagnosticHistory,
  getProvidersStatus,
  getSettingsStatus,
  resetIndexMaintenance,
  testEmbeddingProvider,
  testLlmProvider,
} from "../api/settings.api";
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
import { formatDate } from "../utils/formatDate";

type LoadState =
  | { status: "loading"; health?: ApiResponse<HealthStatus>; settings?: ApiResponse<SettingsStatus>; index?: ApiResponse<IndexStatus>; error?: undefined }
  | {
      status: "online";
      health: ApiResponse<HealthStatus>;
      settings: ApiResponse<SettingsStatus>;
      index: ApiResponse<IndexStatus>;
      providers: ApiResponse<ProvidersStatus>;
      diagnostics: ApiResponse<IndexDiagnostics>;
      collections: ApiResponse<IndexCollections>;
      diagnosticHistory: ApiResponse<ProviderDiagnosticHistory>;
      error?: undefined;
    }
  | { status: "offline"; health?: undefined; settings?: undefined; error: string };

type BusyAction = "embedding" | "llm" | "reset" | null;

export function SettingsPage() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [busyAction, setBusyAction] = useState<BusyAction>(null);
  const [embeddingTest, setEmbeddingTest] = useState<ProviderDiagnostic | null>(null);
  const [llmTest, setLlmTest] = useState<ProviderDiagnostic | null>(null);
  const [maintenanceMessage, setMaintenanceMessage] = useState<string | null>(null);

  const load = async () => {
    setState({ status: "loading" });
    try {
      const [health, settings, index, providers, diagnostics, collections, diagnosticHistory] = await Promise.all([
        getHealth(),
        getSettingsStatus(),
        getIndexStatus(),
        getProvidersStatus(),
        getIndexDiagnostics(),
        getIndexCollections(),
        getProviderDiagnosticHistory(undefined, 10),
      ]);
      setState({ status: "online", health, settings, index, providers, diagnostics, collections, diagnosticHistory });
    } catch (error) {
      setState({
        status: "offline",
        error: error instanceof Error ? error.message : "Connection failed",
      });
    }
  };

  const runEmbeddingTest = async () => {
    setBusyAction("embedding");
    setMaintenanceMessage(null);
    try {
      const response = await testEmbeddingProvider();
      setEmbeddingTest(response.data);
    } catch (error) {
      setMaintenanceMessage(error instanceof Error ? error.message : "Embedding provider test failed");
    } finally {
      if (state.status === "online") {
        try {
          const diagnosticHistory = await getProviderDiagnosticHistory(undefined, 10);
          setState((current) => (current.status === "online" ? { ...current, diagnosticHistory } : current));
        } catch {
          // Keep the diagnostic result visible even if history refresh fails.
        }
      }
      setBusyAction(null);
    }
  };

  const runLlmTest = async () => {
    setBusyAction("llm");
    setMaintenanceMessage(null);
    try {
      const response = await testLlmProvider();
      setLlmTest(response.data);
    } catch (error) {
      setMaintenanceMessage(error instanceof Error ? error.message : "LLM provider test failed");
    } finally {
      if (state.status === "online") {
        try {
          const diagnosticHistory = await getProviderDiagnosticHistory(undefined, 10);
          setState((current) => (current.status === "online" ? { ...current, diagnosticHistory } : current));
        } catch {
          // Keep the diagnostic result visible even if history refresh fails.
        }
      }
      setBusyAction(null);
    }
  };

  const resetIndex = async (collectionName?: string) => {
    if (state.status !== "online") {
      return;
    }
    const targetCollection = collectionName ?? state.diagnostics.data.collection_name;
    const confirmed = window.confirm(
      `Reset index collection "${targetCollection}"?\n\nThis clears Chroma vectors and embedding result metadata only. It does not delete original documents, parsed text, chunks, conversations, or memory.`,
    );
    if (!confirmed) {
      return;
    }

    setBusyAction("reset");
    setMaintenanceMessage(null);
    try {
      const response: ApiResponse<IndexResetResult> = await resetIndexMaintenance({
        confirm: "RESET_INDEX",
        collection_name: targetCollection,
        clear_embedding_results: true,
      });
      setMaintenanceMessage(`Index reset completed. Deleted ${response.data.embedding_results_deleted} embedding result record${response.data.embedding_results_deleted === 1 ? "" : "s"}.`);
      const [index, diagnostics, collections] = await Promise.all([getIndexStatus(), getIndexDiagnostics(), getIndexCollections()]);
      setState((current) => (current.status === "online" ? { ...current, index, diagnostics, collections } : current));
    } catch (error) {
      setMaintenanceMessage(error instanceof Error ? error.message : "Index reset failed");
    } finally {
      setBusyAction(null);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  return (
    <section className="page">
      <header className="page-header row-header">
        <div>
          <p className="eyebrow">Runtime</p>
          <h1>Settings</h1>
        </div>
        <button className="icon-button" type="button" onClick={() => void load()} title="Refresh backend status">
          <RefreshCw size={18} />
        </button>
      </header>

      <div className="status-strip">
        <span className={state.status === "online" ? "status-dot online" : "status-dot"} />
        <div>
          <strong>{state.status === "online" ? "Backend online" : state.status === "loading" ? "Checking backend" : "Backend offline"}</strong>
          <span>{backendUrl}</span>
        </div>
      </div>

      {state.status === "online" ? (
        <>
          <div className="settings-grid">
            <dl>
              <dt>Application</dt>
              <dd>{state.settings.data.app.name}</dd>
              <dt>Version</dt>
              <dd>{state.health.data.version}</dd>
              <dt>Environment</dt>
              <dd>{state.settings.data.app.environment}</dd>
            </dl>
            <dl>
              <dt>Database</dt>
              <dd>{state.settings.data.database.ok ? "OK" : "Unavailable"}</dd>
              <dt>Migration</dt>
              <dd>{state.settings.data.database.migration.up_to_date ? "Up to date" : "Needs upgrade"}</dd>
              <dt>Revision</dt>
              <dd>
                {state.settings.data.database.migration.current_revision ?? "None"} / {state.settings.data.database.migration.head_revision}
              </dd>
              <dt>SQLite Path</dt>
              <dd>{state.settings.data.paths.sqlite_db_path}</dd>
              <dt>OpenAI Configured</dt>
              <dd>{state.settings.data.providers.openai_configured ? "Yes" : "No"}</dd>
              <dt>LLM Provider</dt>
              <dd>{state.settings.data.providers.llm_provider}</dd>
              <dt>Embedding Provider</dt>
              <dd>{state.settings.data.providers.embedding_provider}</dd>
              <dt>Pipeline Worker</dt>
              <dd>
                {state.settings.data.pipeline_worker.running ? "Running" : "Stopped"}, concurrency {state.settings.data.pipeline_worker.concurrency}
              </dd>
              <dt>Worker Lease</dt>
              <dd>{state.settings.data.pipeline_worker.lock_timeout_seconds}s</dd>
            </dl>
            <dl>
              <dt>Upload Limit</dt>
              <dd>{state.settings.data.limits.max_upload_size_mb} MB</dd>
              <dt>Parse Limit</dt>
              <dd>
                {state.settings.data.limits.max_parse_chars} chars, {state.settings.data.limits.max_parse_pages} pages
              </dd>
              <dt>Chunk Limit</dt>
              <dd>
                {state.settings.data.limits.max_chunk_chars} chars, overlap {state.settings.data.limits.chunk_overlap_chars}
              </dd>
              <dt>RAG Limit</dt>
              <dd>
                top {state.settings.data.limits.rag_top_k}, {state.settings.data.limits.rag_max_context_chars} context chars
              </dd>
              <dt>Memory Context</dt>
              <dd>
                {state.settings.data.limits.memory_context_max_chars_per_item} chars each, {state.settings.data.limits.memory_context_max_total_chars} total
              </dd>
              <dt>Chat Context</dt>
              <dd>
                {state.settings.data.limits.chat_context_recent_messages} messages, {state.settings.data.limits.chat_context_max_chars} chars
              </dd>
              <dt>Auto Summary</dt>
              <dd>
                {state.settings.data.limits.auto_summary_enabled ? "Enabled" : "Disabled"}, {state.settings.data.limits.auto_summary_min_new_messages} new /{" "}
                {state.settings.data.limits.auto_summary_min_total_messages} total
              </dd>
            </dl>
            <dl>
              <dt>Chroma Collection</dt>
              <dd>{state.index.data.collection_name}</dd>
              <dt>Vector Path</dt>
              <dd>{state.index.data.persist_path}</dd>
              <dt>Index Status</dt>
              <dd>
                {state.index.data.indexed_document_count} docs, {state.index.data.vector_count} vectors
              </dd>
            </dl>
          </div>

          {maintenanceMessage ? <div className="inline-message">{maintenanceMessage}</div> : null}

          <section className="diagnostics-section">
            <div className="diagnostic-panel">
              <div className="diagnostic-header">
                <div>
                  <p className="eyebrow">Provider Diagnostics</p>
                  <h2>Connectivity</h2>
                </div>
                <Zap size={20} />
              </div>
              <div className="diagnostic-grid">
                <dl>
                  <dt>LLM</dt>
                  <dd>
                    {state.providers.data.llm.provider} / {state.providers.data.llm.model}
                  </dd>
                  <dt>Configured</dt>
                  <dd>{state.providers.data.llm.configured ? "Yes" : state.providers.data.llm.reason ?? "No"}</dd>
                </dl>
                <dl>
                  <dt>Embedding</dt>
                  <dd>
                    {state.providers.data.embedding.provider} / {state.providers.data.embedding.model}
                  </dd>
                  <dt>Configured</dt>
                  <dd>{state.providers.data.embedding.configured ? "Yes" : state.providers.data.embedding.reason ?? "No"}</dd>
                </dl>
              </div>
              <div className="action-group">
                <button className="secondary-button" type="button" onClick={() => void runEmbeddingTest()} disabled={busyAction !== null}>
                  <Activity size={16} />
                  <span>{busyAction === "embedding" ? "Testing" : "Test Embedding"}</span>
                </button>
                <button className="secondary-button" type="button" onClick={() => void runLlmTest()} disabled={busyAction !== null}>
                  <Activity size={16} />
                  <span>{busyAction === "llm" ? "Testing" : "Test LLM"}</span>
                </button>
              </div>
              {embeddingTest ? (
                <div className="diagnostic-result ok">
                  <strong>Embedding OK</strong>
                  <span>
                    {embeddingTest.model}, dimension {embeddingTest.dimension}, {embeddingTest.latency_ms} ms
                  </span>
                </div>
              ) : null}
              {llmTest ? (
                <div className="diagnostic-result ok">
                  <strong>LLM OK</strong>
                  <span>
                    {llmTest.model}, {llmTest.latency_ms} ms, {llmTest.response_preview}
                  </span>
                </div>
              ) : null}
              <div className="diagnostic-list">
                <strong>Recent Provider Checks</strong>
                {state.diagnosticHistory.data.items.length ? (
                  state.diagnosticHistory.data.items.map((item) => (
                    <span key={item.id}>
                      {formatDate(item.created_at)} / {item.provider_kind} / {item.provider}/{item.model} / {item.ok ? "OK" : item.error_message ?? "failed"}
                    </span>
                  ))
                ) : (
                  <span>No provider diagnostics recorded</span>
                )}
              </div>
            </div>

            <div className={state.diagnostics.data.status === "warning" ? "diagnostic-panel warning" : "diagnostic-panel"}>
              <div className="diagnostic-header">
                <div>
                  <p className="eyebrow">Index Diagnostics</p>
                  <h2>{state.diagnostics.data.status === "warning" ? "Warning" : "Healthy"}</h2>
                </div>
                {state.diagnostics.data.status === "warning" ? <AlertTriangle size={20} /> : <Activity size={20} />}
              </div>
              {state.diagnostics.data.warning ? <div className="diagnostic-result warning">{state.diagnostics.data.warning}</div> : null}
              <div className="diagnostic-grid">
                <dl>
                  <dt>Collection</dt>
                  <dd>{state.diagnostics.data.collection_name}</dd>
                  <dt>Vectors</dt>
                  <dd>{state.diagnostics.data.vector_count}</dd>
                  <dt>Dimension</dt>
                  <dd>{state.diagnostics.data.collection_dimension ?? "Empty"}</dd>
                </dl>
                <dl>
                  <dt>Indexed Docs</dt>
                  <dd>{state.diagnostics.data.indexed_document_count}</dd>
                  <dt>DB Dimensions</dt>
                  <dd>{state.diagnostics.data.db_embedding_dimensions.length ? state.diagnostics.data.db_embedding_dimensions.join(", ") : "None"}</dd>
                  <dt>Persist Path</dt>
                  <dd>{state.diagnostics.data.persist_path}</dd>
                </dl>
              </div>
              <div className="diagnostic-list">
                <strong>Collections</strong>
                {state.collections.data.items.length ? (
                  state.collections.data.items.map((collection) => (
                    <div key={collection.name} className="collection-row">
                      <span>
                        {collection.name}
                        {collection.is_current ? " / current" : ""} / {collection.vector_count} vectors / {collection.dimension ?? "empty"} dim / {collection.indexed_document_count} docs
                      </span>
                      <button className="icon-button small danger" type="button" title="Reset collection" onClick={() => void resetIndex(collection.name)} disabled={busyAction !== null}>
                        <Trash2 size={15} />
                      </button>
                    </div>
                  ))
                ) : (
                  <span>No collections found</span>
                )}
              </div>
              <div className="diagnostic-list">
                <strong>Provider / Model Distribution</strong>
                {state.diagnostics.data.provider_model_counts.length ? (
                  state.diagnostics.data.provider_model_counts.map((item) => (
                    <span key={`${item.provider}:${item.model}:${item.status}`}>
                      {item.provider} / {item.model} / {item.status}: {item.count}
                    </span>
                  ))
                ) : (
                  <span>No indexed metadata</span>
                )}
              </div>
              <div className="diagnostic-list">
                <strong>Recent Failures</strong>
                {state.diagnostics.data.recent_failures.length ? (
                  state.diagnostics.data.recent_failures.map((failure) => (
                    <span key={`${failure.document_id}:${failure.updated_at}`}>
                      {formatDate(failure.updated_at)} · {failure.model} · {failure.error_message ?? "failed"}
                    </span>
                  ))
                ) : (
                  <span>No recent index failures</span>
                )}
              </div>
            </div>
          </section>

          <section className="danger-zone">
            <div>
              <p className="eyebrow">Maintenance</p>
              <h2>Reset Current Index</h2>
              <span>Clears Chroma vectors and embedding metadata for the current collection. Documents, parsed text, chunks, chat history, and memory stay untouched.</span>
            </div>
            <button className="secondary-button danger" type="button" onClick={() => void resetIndex()} disabled={busyAction !== null}>
              {busyAction === "reset" ? <RotateCcw size={16} /> : <Trash2 size={16} />}
              <span>{busyAction === "reset" ? "Resetting" : "Reset Index"}</span>
            </button>
          </section>
        </>
      ) : (
        <div className="empty-panel">{state.status === "loading" ? "Loading status" : state.error}</div>
      )}
    </section>
  );
}
