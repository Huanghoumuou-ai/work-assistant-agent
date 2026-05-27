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
import { labelEmbeddingStatus, labelEnvironment, labelProviderKind, onOff, yesNo } from "../utils/labels";

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
        error: error instanceof Error ? error.message : "连接后端失败",
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
      setMaintenanceMessage(error instanceof Error ? error.message : "Embedding 服务商测试失败");
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
      setMaintenanceMessage(error instanceof Error ? error.message : "LLM 服务商测试失败");
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
      `重置索引集合“${targetCollection}”？\n\n这只会清理 Chroma 向量和 embedding 结果元数据，不会删除原始资料、解析文本、切块、对话或记忆。`,
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
      setMaintenanceMessage(`索引已重置。删除 ${response.data.embedding_results_deleted} 条 embedding 结果记录。`);
      const [index, diagnostics, collections] = await Promise.all([getIndexStatus(), getIndexDiagnostics(), getIndexCollections()]);
      setState((current) => (current.status === "online" ? { ...current, index, diagnostics, collections } : current));
    } catch (error) {
      setMaintenanceMessage(error instanceof Error ? error.message : "索引重置失败");
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
          <p className="eyebrow">运行状态</p>
          <h1>设置</h1>
        </div>
        <button className="icon-button" type="button" onClick={() => void load()} title="刷新后端状态">
          <RefreshCw size={18} />
        </button>
      </header>

      <div className="status-strip">
        <span className={state.status === "online" ? "status-dot online" : "status-dot"} />
        <div>
          <strong>{state.status === "online" ? "后端在线" : state.status === "loading" ? "正在检查后端" : "后端离线"}</strong>
          <span>{backendUrl}</span>
        </div>
      </div>

      {state.status === "online" ? (
        <>
          <div className="settings-grid">
            <dl>
              <dt>应用</dt>
              <dd>{state.settings.data.app.name}</dd>
              <dt>版本</dt>
              <dd>{state.health.data.version}</dd>
              <dt>环境</dt>
              <dd>{labelEnvironment(state.settings.data.app.environment)}</dd>
            </dl>
            <dl>
              <dt>数据库</dt>
              <dd>{state.settings.data.database.ok ? "正常" : "不可用"}</dd>
              <dt>迁移</dt>
              <dd>{state.settings.data.database.migration.up_to_date ? "已是最新" : "需要升级"}</dd>
              <dt>版本号</dt>
              <dd>
                {state.settings.data.database.migration.current_revision ?? "无"} / {state.settings.data.database.migration.head_revision}
              </dd>
              <dt>SQLite 路径</dt>
              <dd>{state.settings.data.paths.sqlite_db_path}</dd>
              <dt>OpenAI 已配置</dt>
              <dd>{yesNo(state.settings.data.providers.openai_configured)}</dd>
              <dt>LLM 服务商</dt>
              <dd>{state.settings.data.providers.llm_provider}</dd>
              <dt>Embedding 服务商</dt>
              <dd>{state.settings.data.providers.embedding_provider}</dd>
              <dt>处理工作器</dt>
              <dd>
                {state.settings.data.pipeline_worker.running ? "运行中" : "已停止"}，并发 {state.settings.data.pipeline_worker.concurrency}
              </dd>
              <dt>工作器租约</dt>
              <dd>{state.settings.data.pipeline_worker.lock_timeout_seconds}s</dd>
            </dl>
            <dl>
              <dt>上传限制</dt>
              <dd>{state.settings.data.limits.max_upload_size_mb} MB</dd>
              <dt>解析限制</dt>
              <dd>
                {state.settings.data.limits.max_parse_chars} 字符，{state.settings.data.limits.max_parse_pages} 页
              </dd>
              <dt>切块限制</dt>
              <dd>
                {state.settings.data.limits.max_chunk_chars} 字符，重叠 {state.settings.data.limits.chunk_overlap_chars}
              </dd>
              <dt>RAG 限制</dt>
              <dd>
                前 {state.settings.data.limits.rag_top_k} 条，上下文 {state.settings.data.limits.rag_max_context_chars} 字符
              </dd>
              <dt>查询改写</dt>
              <dd>
                {onOff(state.settings.data.limits.rag_query_rewrite_enabled)}，最多 {state.settings.data.limits.rag_query_rewrite_max_chars} 字符
              </dd>
              <dt>记忆上下文</dt>
              <dd>
                每条 {state.settings.data.limits.memory_context_max_chars_per_item} 字符，总计 {state.settings.data.limits.memory_context_max_total_chars}
              </dd>
              <dt>对话上下文</dt>
              <dd>
                {state.settings.data.limits.chat_context_recent_messages} 条消息，{state.settings.data.limits.chat_context_max_chars} 字符
              </dd>
              <dt>自动摘要</dt>
              <dd>
                {onOff(state.settings.data.limits.auto_summary_enabled)}，新增 {state.settings.data.limits.auto_summary_min_new_messages} / 总计{" "}
                {state.settings.data.limits.auto_summary_min_total_messages}
              </dd>
            </dl>
            <dl>
              <dt>Chroma 集合</dt>
              <dd>{state.index.data.collection_name}</dd>
              <dt>向量路径</dt>
              <dd>{state.index.data.persist_path}</dd>
              <dt>索引状态</dt>
              <dd>
                {state.index.data.indexed_document_count} 份资料，{state.index.data.vector_count} 个向量
              </dd>
            </dl>
          </div>

          {maintenanceMessage ? <div className="inline-message">{maintenanceMessage}</div> : null}

          <section className="diagnostics-section">
            <div className="diagnostic-panel">
              <div className="diagnostic-header">
                <div>
                  <p className="eyebrow">服务商诊断</p>
                  <h2>连通性</h2>
                </div>
                <Zap size={20} />
              </div>
              <div className="diagnostic-grid">
                <dl>
                  <dt>LLM</dt>
                  <dd>
                    {state.providers.data.llm.provider} / {state.providers.data.llm.model}
                  </dd>
                  <dt>已配置</dt>
                  <dd>{state.providers.data.llm.configured ? "是" : state.providers.data.llm.reason ?? "否"}</dd>
                </dl>
                <dl>
                  <dt>Embedding</dt>
                  <dd>
                    {state.providers.data.embedding.provider} / {state.providers.data.embedding.model}
                  </dd>
                  <dt>已配置</dt>
                  <dd>{state.providers.data.embedding.configured ? "是" : state.providers.data.embedding.reason ?? "否"}</dd>
                </dl>
              </div>
              <div className="action-group">
                <button className="secondary-button" type="button" onClick={() => void runEmbeddingTest()} disabled={busyAction !== null}>
                  <Activity size={16} />
                  <span>{busyAction === "embedding" ? "测试中" : "测试 Embedding"}</span>
                </button>
                <button className="secondary-button" type="button" onClick={() => void runLlmTest()} disabled={busyAction !== null}>
                  <Activity size={16} />
                  <span>{busyAction === "llm" ? "测试中" : "测试 LLM"}</span>
                </button>
              </div>
              {embeddingTest ? (
                <div className="diagnostic-result ok">
                  <strong>Embedding 正常</strong>
                  <span>
                    {embeddingTest.model}，维度 {embeddingTest.dimension}，{embeddingTest.latency_ms} ms
                  </span>
                </div>
              ) : null}
              {llmTest ? (
                <div className="diagnostic-result ok">
                  <strong>LLM 正常</strong>
                  <span>
                    {llmTest.model}, {llmTest.latency_ms} ms, {llmTest.response_preview}
                  </span>
                </div>
              ) : null}
              <div className="diagnostic-list">
                <strong>最近服务商检查</strong>
                {state.diagnosticHistory.data.items.length ? (
                  state.diagnosticHistory.data.items.map((item) => (
                    <span key={item.id}>
                      {formatDate(item.created_at)} / {labelProviderKind(item.provider_kind)} / {item.provider}/{item.model} / {item.ok ? "正常" : item.error_message ?? "失败"}
                    </span>
                  ))
                ) : (
                  <span>暂无服务商诊断记录</span>
                )}
              </div>
            </div>

            <div className={state.diagnostics.data.status === "warning" ? "diagnostic-panel warning" : "diagnostic-panel"}>
              <div className="diagnostic-header">
                <div>
                  <p className="eyebrow">索引诊断</p>
                  <h2>{state.diagnostics.data.status === "warning" ? "有警告" : "健康"}</h2>
                </div>
                {state.diagnostics.data.status === "warning" ? <AlertTriangle size={20} /> : <Activity size={20} />}
              </div>
              {state.diagnostics.data.warning ? <div className="diagnostic-result warning">{state.diagnostics.data.warning}</div> : null}
              <div className="diagnostic-grid">
                <dl>
                  <dt>集合</dt>
                  <dd>{state.diagnostics.data.collection_name}</dd>
                  <dt>向量数</dt>
                  <dd>{state.diagnostics.data.vector_count}</dd>
                  <dt>维度</dt>
                  <dd>{state.diagnostics.data.collection_dimension ?? "空"}</dd>
                </dl>
                <dl>
                  <dt>已索引资料</dt>
                  <dd>{state.diagnostics.data.indexed_document_count}</dd>
                  <dt>数据库维度</dt>
                  <dd>{state.diagnostics.data.db_embedding_dimensions.length ? state.diagnostics.data.db_embedding_dimensions.join(", ") : "无"}</dd>
                  <dt>持久化路径</dt>
                  <dd>{state.diagnostics.data.persist_path}</dd>
                </dl>
              </div>
              <div className="diagnostic-list">
                <strong>集合列表</strong>
                {state.collections.data.items.length ? (
                  state.collections.data.items.map((collection) => (
                    <div key={collection.name} className="collection-row">
                      <span>
                        {collection.name}
                        {collection.is_current ? " / 当前" : ""} / {collection.vector_count} 个向量 / {collection.dimension ?? "空"} 维 / {collection.indexed_document_count} 份资料
                      </span>
                      <button className="icon-button small danger" type="button" title="重置集合" onClick={() => void resetIndex(collection.name)} disabled={busyAction !== null}>
                        <Trash2 size={15} />
                      </button>
                    </div>
                  ))
                ) : (
                  <span>未找到集合</span>
                )}
              </div>
              <div className="diagnostic-list">
                <strong>服务商 / 模型分布</strong>
                {state.diagnostics.data.provider_model_counts.length ? (
                  state.diagnostics.data.provider_model_counts.map((item) => (
                    <span key={`${item.provider}:${item.model}:${item.status}`}>
                      {item.provider} / {item.model} / {labelEmbeddingStatus(item.status)}：{item.count}
                    </span>
                  ))
                ) : (
                  <span>暂无索引元数据</span>
                )}
              </div>
              <div className="diagnostic-list">
                <strong>最近失败</strong>
                {state.diagnostics.data.recent_failures.length ? (
                  state.diagnostics.data.recent_failures.map((failure) => (
                    <span key={`${failure.document_id}:${failure.updated_at}`}>
                      {formatDate(failure.updated_at)} / {failure.model} / {failure.error_message ?? "失败"}
                    </span>
                  ))
                ) : (
                  <span>最近没有索引失败</span>
                )}
              </div>
            </div>
          </section>

          <section className="danger-zone">
            <div>
              <p className="eyebrow">维护</p>
              <h2>重置当前索引</h2>
              <span>清理当前集合的 Chroma 向量和 embedding 元数据。资料、解析文本、切块、聊天记录和记忆都会保留。</span>
            </div>
            <button className="secondary-button danger" type="button" onClick={() => void resetIndex()} disabled={busyAction !== null}>
              {busyAction === "reset" ? <RotateCcw size={16} /> : <Trash2 size={16} />}
              <span>{busyAction === "reset" ? "重置中" : "重置索引"}</span>
            </button>
          </section>
        </>
      ) : (
        <div className="empty-panel">{state.status === "loading" ? "正在加载状态" : state.error}</div>
      )}
    </section>
  );
}
