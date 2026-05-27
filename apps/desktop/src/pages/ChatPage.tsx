import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronRight, FileText, MessageSquarePlus, RefreshCw, Send, SlidersHorizontal } from "lucide-react";

import { generateConversationSummary, getConversationMessages, getConversationSummary, getConversations, streamChat } from "../api/chat.api";
import { getChunkContent } from "../api/documents.api";
import { getMemory } from "../api/memory.api";
import { getProjects } from "../api/projects.api";
import type { ChatMessage, ConversationItem, ConversationSummary, ProjectItem } from "../types/api";
import { formatDate } from "../utils/formatDate";

const DEFAULT_TOP_K = 5;

type BusyState = "boot" | "conversations" | "messages" | "send" | "summary" | null;

function sourceSummary(text: string) {
  const compact = text.replace(/\s+/g, " ").trim();
  if (!compact) {
    return "Source excerpt";
  }
  return compact.length > 42 ? `${compact.slice(0, 42).trim()}...` : compact;
}

export function ChatPage() {
  const threadRef = useRef<HTMLDivElement | null>(null);
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
      setMessage(error instanceof Error ? error.message : "Failed to refresh chat data");
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
      setMessage(error instanceof Error ? error.message : "Failed to load messages");
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
      setMessage("Question is required");
      return;
    }

    setBusy("send");
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
              throw new Error(event.data.message ?? "Chat request failed");
            }
          },
        },
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Chat request failed");
    } finally {
      setPendingPrompt(null);
      setStreamingAnswer("");
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
      setMessage(error instanceof Error ? error.message : "Summary request failed");
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
        [sourceKey]: { loading: false, error: error instanceof Error ? error.message : "Failed to load chunk" },
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
        [sourceKey]: { loading: false, error: error instanceof Error ? error.message : "Failed to load memory" },
      }));
    }
  };

  useEffect(() => {
    setBusy("boot");
    void Promise.all([loadProjects(), loadConversationList()])
      .then(() => setMessage(null))
      .catch((error) => setMessage(error instanceof Error ? error.message : "Failed to load chat data"))
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
            <span>Local Chat</span>
          </div>
          <button className="icon-button small" type="button" onClick={startNewConversation} title="New conversation" disabled={busy === "send"}>
            <MessageSquarePlus size={16} />
          </button>
        </div>
        <button className="secondary-button full-button" type="button" onClick={() => void refreshAll()} disabled={busy !== null}>
          <RefreshCw size={16} />
          <span>{busy === "boot" || busy === "conversations" ? "Refreshing" : "Refresh"}</span>
        </button>
        <div className="conversation-section-label">Recent</div>
        <div className="conversation-list">
          {conversations.length === 0 ? (
            <div className="empty-panel compact">No conversations yet</div>
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
            <p className="eyebrow">Phase 13</p>
            <h1>{activeConversation ? activeConversation.title : "New chat"}</h1>
          </div>
          <div className="action-group">
            <button className={showSummary ? "secondary-button active" : "secondary-button"} type="button" onClick={() => setShowSummary((value) => !value)} disabled={!activeConversation}>
              <FileText size={16} />
              <span>Summary</span>
            </button>
            <button className={showControls ? "secondary-button active" : "secondary-button"} type="button" onClick={() => setShowControls((value) => !value)}>
              <SlidersHorizontal size={16} />
              <span>Options</span>
            </button>
          </div>
        </header>

        {showControls ? (
          <div className="chat-options">
            <label>
              <span>Project</span>
              <select value={projectId} onChange={(event) => setProjectId(event.target.value)} disabled={busy === "send"}>
                <option value="">All uploaded documents</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Document ID</span>
              <input value={documentId} onChange={(event) => setDocumentId(event.target.value)} placeholder="Optional exact document id" disabled={busy === "send"} />
            </label>
            <label>
              <span>Top K</span>
              <input type="number" min={1} max={20} value={topK} onChange={(event) => setTopK(Number(event.target.value))} disabled={busy === "send"} />
            </label>
            <label>
              <span>Memory</span>
              <select value={includeMemory ? "on" : "off"} onChange={(event) => setIncludeMemory(event.target.value === "on")} disabled={busy === "send"}>
                <option value="off">Off</option>
                <option value="on">On</option>
              </select>
            </label>
            <label>
              <span>Memory Limit</span>
              <input type="number" min={1} max={20} value={memoryLimit} onChange={(event) => setMemoryLimit(Number(event.target.value))} disabled={busy === "send" || !includeMemory} />
            </label>
            <label>
              <span>Auto Summary</span>
              <select value={autoSummary ? "on" : "off"} onChange={(event) => setAutoSummary(event.target.value === "on")} disabled={busy === "send"}>
                <option value="off">Off</option>
                <option value="on">On</option>
              </select>
            </label>
          </div>
        ) : null}

        {showSummary && activeConversation ? (
          <section className="summary-drawer">
            <div className="chat-actions">
              <span>Conversation Summary</span>
              <button className="secondary-button" type="button" onClick={() => void refreshSummary()} disabled={busy !== null}>
                <FileText size={16} />
                <span>{busy === "summary" ? "Generating" : summary ? "Refresh" : "Generate"}</span>
              </button>
            </div>
            {summary ? (
              <div className="summary-panel">
                <dl>
                  <dt>Status</dt>
                  <dd>{summary.status}</dd>
                  <dt>Generated</dt>
                  <dd>{summary.generated_at ? formatDate(summary.generated_at) : "Not generated"}</dd>
                  <dt>Coverage</dt>
                  <dd>
                    {summary.message_count} messages, {summary.stale ? "stale" : "current"}
                  </dd>
                  <dt>New Messages</dt>
                  <dd>
                    {summary.new_message_count}, {summary.needs_refresh ? "needs refresh" : "within threshold"}
                  </dd>
                </dl>
                {summary.status === "failed" ? (
                  <div className="inline-message">{summary.error_message ?? "Summary generation failed"}</div>
                ) : summary.status === "missing" ? (
                  <div className="empty-panel compact">No summary generated</div>
                ) : (
                  <p>{summary.summary}</p>
                )}
              </div>
            ) : (
              <div className="empty-panel compact">No summary generated</div>
            )}
          </section>
        ) : null}

        {message ? <div className="inline-message">{message}</div> : null}

        <div className="chat-thread" ref={threadRef}>
          {busy === "messages" ? (
            <div className="empty-panel compact">Loading messages</div>
          ) : messages.length === 0 && !pendingPrompt ? (
            <div className="chat-empty-state">
              <h2>Ask your indexed work knowledge base.</h2>
              <p>Upload, parse, chunk, and index documents first. Then ask a question here.</p>
            </div>
          ) : (
            <>
              {messages.map((item) => (
                <article className={item.role === "assistant" ? "chat-message assistant" : "chat-message user"} key={item.id}>
                  <div className="chat-avatar">{item.role === "assistant" ? "AI" : "You"}</div>
                  <div className="chat-message-body">
                    <div className="message-meta">
                      <strong>{item.role === "assistant" ? "Assistant" : "You"}</strong>
                      <span>{formatDate(item.created_at)}</span>
                    </div>
                    <p>{item.content}</p>
                    {item.role === "assistant" && item.provider ? (
                      <span className="model-line">
                        {item.provider} / {item.model}
                      </span>
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
                                title={`${source.source_filename} · chunk #${source.chunk_index} · score ${source.score.toFixed(4)}`}
                              >
                                {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                <strong>{source.source_id}：</strong>
                                <span>{sourceSummary(source.excerpt)}--{source.source_filename}</span>
                              </button>
                              {expanded ? (
                                <div className="citation-detail">
                                  <dl>
                                    <dt>File</dt>
                                    <dd>{source.source_filename}</dd>
                                    <dt>Project</dt>
                                    <dd>{source.project_id ? projectNameById.get(source.project_id) ?? source.project_id : "Unfiled"}</dd>
                                    <dt>Uploaded</dt>
                                    <dd>{formatDate(source.uploaded_at)}</dd>
                                    <dt>Chunk</dt>
                                    <dd>
                                      #{source.chunk_index}, chars {source.char_start}-{source.char_end}
                                    </dd>
                                    <dt>Score</dt>
                                    <dd>
                                      {source.score.toFixed(4)} / distance {source.distance.toFixed(4)}
                                    </dd>
                                  </dl>
                                  <p>
                                    {sourceDetails[sourceKey]?.loading
                                      ? "Loading full chunk..."
                                      : sourceDetails[sourceKey]?.error ?? sourceDetails[sourceKey]?.content ?? source.excerpt}
                                  </p>
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
                                title={`${source.type} · ${source.project_name ?? "Global"}`}
                              >
                                {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                <strong>{source.source_id}：</strong>
                                <span>{sourceSummary(source.content)}--{source.title}</span>
                              </button>
                              {expanded ? (
                                <div className="citation-detail">
                                  <dl>
                                    <dt>Title</dt>
                                    <dd>{source.title}</dd>
                                    <dt>Type</dt>
                                    <dd>{source.type}</dd>
                                    <dt>Project</dt>
                                    <dd>{source.project_name ?? (source.project_id ? projectNameById.get(source.project_id) ?? source.project_id : "Global")}</dd>
                                    <dt>Occurred</dt>
                                    <dd>{source.occurred_at ? formatDate(source.occurred_at) : "Not set"}</dd>
                                  </dl>
                                  <p>
                                    {sourceDetails[sourceKey]?.loading
                                      ? "Loading full memory..."
                                      : sourceDetails[sourceKey]?.error ?? sourceDetails[sourceKey]?.content ?? source.content}
                                  </p>
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
                    <div className="chat-avatar">You</div>
                    <div className="chat-message-body">
                      <div className="message-meta">
                        <strong>You</strong>
                        <span>sending</span>
                      </div>
                      <p>{pendingPrompt}</p>
                    </div>
                  </article>
                  <article className="chat-message assistant pending">
                    <div className="chat-avatar">AI</div>
                    <div className="chat-message-body thinking-row">
                      <div className="message-meta">
                        <strong>Thinking</strong>
                        <span>{streamingAnswer ? "streaming answer" : "generating answer"}</span>
                      </div>
                      {streamingAnswer ? (
                        <p className="streaming-answer">{streamingAnswer}</p>
                      ) : (
                        <div className="typing-indicator" aria-label="Waiting for response">
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
            placeholder={activeConversation ? "Message WorkMemory" : "Ask from indexed knowledge"}
            disabled={busy === "send"}
          />
          <div className="composer-footer">
            <span className="composer-mode-label">RAG answer</span>
            <button className="send-button" type="submit" disabled={busy === "send" || !query.trim()}>
              {busy === "send" ? <RefreshCw size={18} /> : <Send size={18} />}
            </button>
          </div>
        </form>
      </main>
    </section>
  );
}
