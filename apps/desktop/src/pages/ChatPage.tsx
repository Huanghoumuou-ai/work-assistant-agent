import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, ChevronRight, Clipboard, FileText, Lightbulb, MessageSquarePlus, Pencil, RefreshCw, RotateCcw, Send, SlidersHorizontal, Square, Trash2 } from "lucide-react";

import { deleteConversation, generateConversationSummary, getConversationMessages, getConversationSummary, getConversations, regenerateConversation, streamChat, updateConversationTitle } from "../api/chat.api";
import { getChunkContent } from "../api/documents.api";
import { generateMemorySuggestionsFromConversation, getMemory } from "../api/memory.api";
import { getProjects } from "../api/projects.api";
import type { ChatMessage, ConversationItem, ConversationSummary, ProjectItem } from "../types/api";
import { formatDate } from "../utils/formatDate";
import { labelMemoryType, labelSummaryStatus } from "../utils/labels";

const DEFAULT_TOP_K = 5;

type BusyState = "boot" | "conversations" | "messages" | "send" | "summary" | "suggestions" | null;

function sourceSummary(text: string) {
  const compact = text.replace(/\s+/g, " ").trim();
  if (!compact) {
    return "来源摘录";
  }
  return compact.length > 42 ? `${compact.slice(0, 42).trim()}...` : compact;
}

export function ChatPage() {
  const threadRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activeConversation, setActiveConversation] = useState<ConversationItem | null>(null);
  const [summary, setSummary] = useState<ConversationSummary | null>(null);
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(DEFAULT_TOP_K);
  const [includeMemory, setIncludeMemory] = useState(false);
  const [memoryLimit, setMemoryLimit] = useState(5);
  const [autoSummary, setAutoSummary] = useState(false);
  const [projectId, setProjectId] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [showControls, setShowControls] = useState(false);
  const [showSummary, setShowSummary] = useState(false);
  const [busy, setBusy] = useState<BusyState>("boot");
  const [message, setMessage] = useState<string | null>(null);
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null);
  const [streamingAnswer, setStreamingAnswer] = useState("");
  const [expandedSources, setExpandedSources] = useState<Set<string>>(new Set());
  const [sourceDetails, setSourceDetails] = useState<Record<string, { loading: boolean; content?: string; error?: string }>>({});
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const projectNameById = useMemo(() => {
    return new Map(projects.map((project) => [project.id, project.name]));
  }, [projects]);

  const loadProjects = async () => {
    const response = await getProjects();
    setProjects(response.data);
  };

  const loadConversationList = async () => {
    const response = await getConversations();
    setConversations(response.data.items);
  };

  const loadSummary = async (conversationId: string) => {
    try {
      const response = await getConversationSummary(conversationId);
      setSummary(response.data);
    } catch (error) {
      if (error instanceof Error && error.message.includes("not found")) {
        setSummary(null);
        return;
      }
      throw error;
    }
  };

  const refreshAll = async () => {
    setBusy("conversations");
    try {
      await Promise.all([loadProjects(), loadConversationList()]);
      setMessage(null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "刷新对话数据失败");
    } finally {
      setBusy(null);
    }
  };

  const openConversation = async (conversation: ConversationItem) => {
    setBusy("messages");
    setMessage(null);
    try {
      const response = await getConversationMessages(conversation.id);
      await loadSummary(conversation.id);
      setActiveConversation(response.data.conversation);
      setMessages(response.data.messages);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "消息加载失败");
    } finally {
      setBusy(null);
    }
  };

  const startNewConversation = () => {
    setActiveConversation(null);
    setSummary(null);
    setMessages([]);
    setQuery("");
    setMessage(null);
  };

  const upsertConversation = (conversation: ConversationItem) => {
    setConversations((current) => {
      const next = [conversation, ...current.filter((item) => item.id !== conversation.id)];
      return next.sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));
    });
  };

  const ask = async () => {
    const cleanQuery = query.trim();
    if (!cleanQuery || busy === "send") {
      setMessage("请输入问题");
      return;
    }

    setBusy("send");
    const controller = new AbortController();
    abortRef.current = controller;
    setPendingPrompt(cleanQuery);
    setStreamingAnswer("");
    setMessage(null);
    try {
      setQuery("");
      await streamChat(
        {
          conversation_id: activeConversation?.id ?? null,
          query: cleanQuery,
          top_k: topK,
          project_id: projectId || null,
          document_id: documentId.trim() || null,
          include_memory: includeMemory,
          memory_limit: memoryLimit,
          auto_summary: autoSummary,
        },
        {
          onEvent: (event) => {
            if (event.event === "token") {
              setStreamingAnswer((current) => `${current}${event.data.delta}`);
              return;
            }
            if (event.event === "done") {
              setActiveConversation(event.data.conversation);
              upsertConversation(event.data.conversation);
              setMessages((current) => [...current, event.data.user_message, event.data.assistant_message]);
              setSummary(event.data.summary ?? null);
              return;
            }
            if (event.event === "error") {
              throw new Error(event.data.message ?? "对话请求失败");
            }
          },
          signal: controller.signal,
        },
      );
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        setMessage("已停止生成，未保存不完整回答。");
      } else {
        setMessage(error instanceof Error ? error.message : "对话请求失败");
      }
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
      }
      setPendingPrompt(null);
      setStreamingAnswer("");
      setBusy(null);
    }
  };

  const stopGenerating = () => {
    abortRef.current?.abort();
  };

  const copyText = async (key: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedKey(key);
      window.setTimeout(() => setCopiedKey((current) => (current === key ? null : current)), 1400);
    } catch {
      setMessage("复制失败");
    }
  };

  const renameActiveConversation = async () => {
    if (!activeConversation || busy !== null) {
      return;
    }
    const title = window.prompt("重命名对话", activeConversation.title);
    if (title === null) {
      return;
    }
    setBusy("conversations");
    setMessage(null);
    try {
      const response = await updateConversationTitle(activeConversation.id, title);
      setActiveConversation(response.data);
      upsertConversation(response.data);
      setMessage("对话已重命名");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "重命名失败");
    } finally {
      setBusy(null);
    }
  };

  const deleteActiveConversation = async () => {
    if (!activeConversation || busy !== null) {
      return;
    }
    const confirmed = window.confirm(`删除对话“${activeConversation.title}”？这会同时删除消息和摘要。`);
    if (!confirmed) {
      return;
    }
    const conversationId = activeConversation.id;
    setBusy("conversations");
    setMessage(null);
    try {
      await deleteConversation(conversationId);
      setConversations((current) => current.filter((item) => item.id !== conversationId));
      setActiveConversation(null);
      setSummary(null);
      setMessages([]);
      setMessage("对话已删除");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除失败");
    } finally {
      setBusy(null);
    }
  };

  const regenerateLatest = async () => {
    if (!activeConversation || busy !== null) {
      return;
    }
    setBusy("send");
    setMessage(null);
    setStreamingAnswer("");
    try {
      const response = await regenerateConversation(activeConversation.id, {
        top_k: topK,
        project_id: projectId || null,
        document_id: documentId.trim() || null,
        include_memory: includeMemory,
        memory_limit: memoryLimit,
        auto_summary: autoSummary,
      });
      setActiveConversation(response.data.conversation);
      upsertConversation(response.data.conversation);
      setMessages((current) => {
        const trimmed = [...current];
        while (trimmed.length > 0 && trimmed[trimmed.length - 1].role === "assistant") {
          trimmed.pop();
        }
        return [...trimmed, response.data.assistant_message];
      });
      setSummary(response.data.summary ?? null);
      setMessage("回答已重新生成");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "重新生成失败");
    } finally {
      setBusy(null);
    }
  };

  const suggestMemories = async () => {
    if (!activeConversation || busy !== null) {
      return;
    }
    setBusy("suggestions");
    setMessage(null);
    try {
      const response = await generateMemorySuggestionsFromConversation(activeConversation.id, 5);
      setMessage(`已生成 ${response.data.total} 条待审核工作建议`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "建议生成失败");
    } finally {
      setBusy(null);
    }
  };

  const refreshSummary = async () => {
    if (!activeConversation || busy !== null) {
      return;
    }
    setBusy("summary");
    setMessage(null);
    try {
      const response = await generateConversationSummary(activeConversation.id);
      setSummary(response.data);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "摘要请求失败");
    } finally {
      setBusy(null);
    }
  };

  const toggleSource = (sourceKey: string) => {
    setExpandedSources((current) => {
      const next = new Set(current);
      if (next.has(sourceKey)) {
        next.delete(sourceKey);
      } else {
        next.add(sourceKey);
      }
      return next;
    });
  };

  const loadChunkDetail = async (sourceKey: string, chunkId: string) => {
    if (sourceDetails[sourceKey]?.content || sourceDetails[sourceKey]?.loading) {
      return;
    }
    setSourceDetails((current) => ({ ...current, [sourceKey]: { loading: true } }));
    try {
      const response = await getChunkContent(chunkId);
      setSourceDetails((current) => ({ ...current, [sourceKey]: { loading: false, content: response.data.content } }));
    } catch (error) {
      setSourceDetails((current) => ({
        ...current,
        [sourceKey]: { loading: false, error: error instanceof Error ? error.message : "切块加载失败" },
      }));
    }
  };

  const loadMemoryDetail = async (sourceKey: string, memoryId: string) => {
    if (sourceDetails[sourceKey]?.content || sourceDetails[sourceKey]?.loading) {
      return;
    }
    setSourceDetails((current) => ({ ...current, [sourceKey]: { loading: true } }));
    try {
      const response = await getMemory(memoryId);
      setSourceDetails((current) => ({ ...current, [sourceKey]: { loading: false, content: response.data.content } }));
    } catch (error) {
      setSourceDetails((current) => ({
        ...current,
        [sourceKey]: { loading: false, error: error instanceof Error ? error.message : "记忆加载失败" },
      }));
    }
  };

  useEffect(() => {
    setBusy("boot");
    void Promise.all([loadProjects(), loadConversationList()])
      .then(() => setMessage(null))
      .catch((error) => setMessage(error instanceof Error ? error.message : "对话数据加载失败"))
      .finally(() => setBusy(null));
  }, []);

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, pendingPrompt, streamingAnswer]);

  return (
    <section className="chat-page">
      <aside className="conversation-panel chat-history-panel">
        <div className="chat-history-header">
          <div>
            <strong>WorkMemory</strong>
            <span>本地问答</span>
          </div>
          <button className="icon-button small" type="button" onClick={startNewConversation} title="新建对话" disabled={busy === "send"}>
            <MessageSquarePlus size={16} />
          </button>
        </div>
        <button className="secondary-button full-button" type="button" onClick={() => void refreshAll()} disabled={busy !== null}>
          <RefreshCw size={16} />
          <span>{busy === "boot" || busy === "conversations" ? "刷新中" : "刷新"}</span>
        </button>
        <div className="conversation-section-label">最近对话</div>
        <div className="conversation-list">
          {conversations.length === 0 ? (
            <div className="empty-panel compact">还没有对话</div>
          ) : (
            conversations.map((conversation) => (
              <button
                key={conversation.id}
                className={activeConversation?.id === conversation.id ? "conversation-item active" : "conversation-item"}
                type="button"
                onClick={() => void openConversation(conversation)}
                disabled={busy === "send"}
                title={`${conversation.title} · ${formatDate(conversation.updated_at)}`}
              >
                <strong>{conversation.title}</strong>
              </button>
            ))
          )}
        </div>
      </aside>

      <main className="chat-canvas">
        <header className="chat-topbar">
          <div>
            <p className="eyebrow">RAG 问答</p>
            <h1>{activeConversation ? activeConversation.title : "新对话"}</h1>
          </div>
          <div className="action-group">
            <button className={showSummary ? "secondary-button active" : "secondary-button"} type="button" onClick={() => setShowSummary((value) => !value)} disabled={!activeConversation}>
              <FileText size={16} />
              <span>摘要</span>
            </button>
            <button className="secondary-button" type="button" onClick={() => void suggestMemories()} disabled={!activeConversation || busy !== null}>
              <Lightbulb size={16} />
              <span>{busy === "suggestions" ? "建议生成中" : "生成建议"}</span>
            </button>
            <button className="icon-button" type="button" onClick={() => void renameActiveConversation()} disabled={!activeConversation || busy !== null} title="重命名对话">
              <Pencil size={16} />
            </button>
            <button className="icon-button danger" type="button" onClick={() => void deleteActiveConversation()} disabled={!activeConversation || busy !== null} title="删除对话">
              <Trash2 size={16} />
            </button>
            <button className={showControls ? "secondary-button active" : "secondary-button"} type="button" onClick={() => setShowControls((value) => !value)}>
              <SlidersHorizontal size={16} />
              <span>选项</span>
            </button>
          </div>
        </header>

        {showControls ? (
          <div className="chat-options">
            <label>
              <span>项目</span>
              <select value={projectId} onChange={(event) => setProjectId(event.target.value)} disabled={busy === "send"}>
                <option value="">全部已上传资料</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>资料 ID</span>
              <input value={documentId} onChange={(event) => setDocumentId(event.target.value)} placeholder="可选，精确资料 ID" disabled={busy === "send"} />
            </label>
            <label>
              <span>返回数量</span>
              <input type="number" min={1} max={20} value={topK} onChange={(event) => setTopK(Number(event.target.value))} disabled={busy === "send"} />
            </label>
            <label>
              <span>记忆</span>
              <select value={includeMemory ? "on" : "off"} onChange={(event) => setIncludeMemory(event.target.value === "on")} disabled={busy === "send"}>
                <option value="off">关闭</option>
                <option value="on">开启</option>
              </select>
            </label>
            <label>
              <span>记忆数量</span>
              <input type="number" min={1} max={20} value={memoryLimit} onChange={(event) => setMemoryLimit(Number(event.target.value))} disabled={busy === "send" || !includeMemory} />
            </label>
            <label>
              <span>自动摘要</span>
              <select value={autoSummary ? "on" : "off"} onChange={(event) => setAutoSummary(event.target.value === "on")} disabled={busy === "send"}>
                <option value="off">关闭</option>
                <option value="on">开启</option>
              </select>
            </label>
          </div>
        ) : null}

        {showSummary && activeConversation ? (
          <section className="summary-drawer">
            <div className="chat-actions">
              <span>对话摘要</span>
              <button className="secondary-button" type="button" onClick={() => void refreshSummary()} disabled={busy !== null}>
                <FileText size={16} />
                <span>{busy === "summary" ? "生成中" : summary ? "刷新" : "生成"}</span>
              </button>
            </div>
            {summary ? (
              <div className="summary-panel">
                <dl>
                  <dt>状态</dt>
                  <dd>{labelSummaryStatus(summary.status)}</dd>
                  <dt>生成时间</dt>
                  <dd>{summary.generated_at ? formatDate(summary.generated_at) : "未生成"}</dd>
                  <dt>覆盖范围</dt>
                  <dd>
                    {summary.message_count} 条消息，{summary.stale ? "已过期" : "当前"}
                  </dd>
                  <dt>新增消息</dt>
                  <dd>
                    {summary.new_message_count} 条，{summary.needs_refresh ? "需要刷新" : "未达阈值"}
                  </dd>
                </dl>
                {summary.status === "failed" ? (
                  <div className="inline-message">{summary.error_message ?? "摘要生成失败"}</div>
                ) : summary.status === "missing" ? (
                  <div className="empty-panel compact">还没有生成摘要</div>
                ) : (
                  <p>{summary.summary}</p>
                )}
              </div>
            ) : (
              <div className="empty-panel compact">还没有生成摘要</div>
            )}
          </section>
        ) : null}

        {message ? <div className="inline-message">{message}</div> : null}

        <div className="chat-thread" ref={threadRef}>
          {busy === "messages" ? (
            <div className="empty-panel compact">正在加载消息</div>
          ) : messages.length === 0 && !pendingPrompt ? (
            <div className="chat-empty-state">
              <h2>向已索引的工作知识库提问。</h2>
              <p>先上传、解析、切块并索引资料，然后在这里提问。</p>
            </div>
          ) : (
            <>
              {messages.map((item) => (
                <article className={item.role === "assistant" ? "chat-message assistant" : "chat-message user"} key={item.id}>
                  <div className="chat-avatar">{item.role === "assistant" ? "AI" : "我"}</div>
                  <div className="chat-message-body">
                    <div className="message-meta">
                      <strong>{item.role === "assistant" ? "助手" : "我"}</strong>
                      <span>{formatDate(item.created_at)}</span>
                    </div>
                    <p>{item.content}</p>
                    {item.role === "assistant" && item.provider ? (
                      <span className="model-line">
                        {item.provider} / {item.model}
                      </span>
                    ) : null}
                    {item.role === "assistant" ? (
                      <div className="message-actions">
                        <button className="icon-button small" type="button" title="复制回答" onClick={() => void copyText(`answer:${item.id}`, item.content)}>
                          {copiedKey === `answer:${item.id}` ? <Check size={15} /> : <Clipboard size={15} />}
                        </button>
                        {item.id === messages[messages.length - 1]?.id ? (
                          <button className="icon-button small" type="button" title="重新生成回答" onClick={() => void regenerateLatest()} disabled={busy !== null || !activeConversation}>
                            <RotateCcw size={15} />
                          </button>
                        ) : null}
                      </div>
                    ) : null}
                    {item.sources.length > 0 ? (
                      <div className="citation-list">
                        {item.sources.map((source) => {
                          const sourceKey = `${item.id}:${source.source_id}:${source.chunk_id}`;
                          const expanded = expandedSources.has(sourceKey);
                          return (
                            <div className="citation-item" key={sourceKey}>
                              <button
                                className="citation-row"
                                type="button"
                                onClick={() => {
                                  const willExpand = !expandedSources.has(sourceKey);
                                  toggleSource(sourceKey);
                                  if (willExpand) {
                                    void loadChunkDetail(sourceKey, source.chunk_id);
                                  }
                                }}
                                title={`${source.source_filename} · 切块 #${source.chunk_index} · 分数 ${source.score.toFixed(4)}`}
                              >
                                {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                <strong>{source.source_id}：</strong>
                                <span>{sourceSummary(source.excerpt)}--{source.source_filename}</span>
                              </button>
                              {expanded ? (
                                <div className="citation-detail">
                                  <dl>
                                    <dt>文件</dt>
                                    <dd>{source.source_filename}</dd>
                                    <dt>项目</dt>
                                    <dd>{source.project_id ? projectNameById.get(source.project_id) ?? source.project_id : "未归档"}</dd>
                                    <dt>上传时间</dt>
                                    <dd>{formatDate(source.uploaded_at)}</dd>
                                    <dt>切块</dt>
                                    <dd>
                                      #{source.chunk_index}，字符 {source.char_start}-{source.char_end}
                                    </dd>
                                    <dt>分数</dt>
                                    <dd>
                                      {source.score.toFixed(4)} / 距离 {source.distance.toFixed(4)}
                                    </dd>
                                  </dl>
                                  <p>
                                    {sourceDetails[sourceKey]?.loading
                                      ? "正在加载完整切块..."
                                      : sourceDetails[sourceKey]?.error ?? sourceDetails[sourceKey]?.content ?? source.excerpt}
                                  </p>
                                  <button
                                    className="secondary-button compact-button"
                                    type="button"
                                    onClick={() =>
                                      void copyText(
                                        `source:${sourceKey}`,
                                        `${source.source_id} ${source.source_filename} document=${source.document_id} chunk=${source.chunk_id} score=${source.score.toFixed(4)} excerpt=${source.excerpt}`,
                                      )
                                    }
                                  >
                                    {copiedKey === `source:${sourceKey}` ? <Check size={14} /> : <Clipboard size={14} />}
                                    <span>复制引用</span>
                                  </button>
                                </div>
                              ) : null}
                            </div>
                          );
                        })}
                      </div>
                    ) : null}
                    {item.memory_sources.length > 0 ? (
                      <div className="citation-list">
                        {item.memory_sources.map((source) => {
                          const sourceKey = `${item.id}:${source.source_id}:${source.memory_id}`;
                          const expanded = expandedSources.has(sourceKey);
                          return (
                            <div className="citation-item" key={sourceKey}>
                              <button
                                className="citation-row memory"
                                type="button"
                                onClick={() => {
                                  const willExpand = !expandedSources.has(sourceKey);
                                  toggleSource(sourceKey);
                                  if (willExpand) {
                                    void loadMemoryDetail(sourceKey, source.memory_id);
                                  }
                                }}
                                title={`${labelMemoryType(source.type)} · ${source.project_name ?? "全局"}`}
                              >
                                {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                <strong>{source.source_id}：</strong>
                                <span>{sourceSummary(source.content)}--{source.title}</span>
                              </button>
                              {expanded ? (
                                <div className="citation-detail">
                                  <dl>
                                    <dt>标题</dt>
                                    <dd>{source.title}</dd>
                                    <dt>类型</dt>
                                    <dd>{labelMemoryType(source.type)}</dd>
                                    <dt>项目</dt>
                                    <dd>{source.project_name ?? (source.project_id ? projectNameById.get(source.project_id) ?? source.project_id : "全局")}</dd>
                                    <dt>发生时间</dt>
                                    <dd>{source.occurred_at ? formatDate(source.occurred_at) : "未设置"}</dd>
                                  </dl>
                                  <p>
                                    {sourceDetails[sourceKey]?.loading
                                      ? "正在加载完整记忆..."
                                      : sourceDetails[sourceKey]?.error ?? sourceDetails[sourceKey]?.content ?? source.content}
                                  </p>
                                  <button
                                    className="secondary-button compact-button"
                                    type="button"
                                    onClick={() =>
                                      void copyText(
                                        `memory:${sourceKey}`,
                                        `${source.source_id} ${source.title} memory=${source.memory_id} type=${source.type} score=${source.score.toFixed(2)} content=${source.content}`,
                                      )
                                    }
                                  >
                                    {copiedKey === `memory:${sourceKey}` ? <Check size={14} /> : <Clipboard size={14} />}
                                    <span>复制引用</span>
                                  </button>
                                </div>
                              ) : null}
                            </div>
                          );
                        })}
                      </div>
                    ) : null}
                  </div>
                </article>
              ))}
              {pendingPrompt ? (
                <>
                  <article className="chat-message user pending">
                    <div className="chat-avatar">我</div>
                    <div className="chat-message-body">
                      <div className="message-meta">
                        <strong>我</strong>
                        <span>发送中</span>
                      </div>
                      <p>{pendingPrompt}</p>
                    </div>
                  </article>
                  <article className="chat-message assistant pending">
                    <div className="chat-avatar">AI</div>
                    <div className="chat-message-body thinking-row">
                      <div className="message-meta">
                        <strong>思考中</strong>
                        <span>{streamingAnswer ? "正在输出回答" : "正在生成回答"}</span>
                      </div>
                      {streamingAnswer ? (
                        <p className="streaming-answer">{streamingAnswer}</p>
                      ) : (
                        <div className="typing-indicator" aria-label="等待回答">
                          <span />
                          <span />
                          <span />
                        </div>
                      )}
                    </div>
                  </article>
                </>
              ) : null}
            </>
          )}
        </div>

        <form
          className="chat-composer"
          onSubmit={(event) => {
            event.preventDefault();
            void ask();
          }}
        >
          <textarea
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void ask();
              }
            }}
            placeholder={activeConversation ? "给 WorkMemory 发送消息" : "向已索引知识提问"}
            disabled={busy === "send"}
          />
          <div className="composer-footer">
            <span className="composer-mode-label">RAG 回答</span>
            {busy === "send" ? (
              <button className="send-button stop" type="button" onClick={stopGenerating} title="停止生成">
                <Square size={16} />
              </button>
            ) : (
              <button className="send-button" type="submit" disabled={!query.trim()}>
                <Send size={18} />
              </button>
            )}
          </div>
        </form>
      </main>
    </section>
  );
}
