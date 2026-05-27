import { useEffect, useRef, useState } from "react";
import { Archive, CheckCircle2, Lightbulb, RefreshCw, RotateCcw, Save, Search, X, XCircle } from "lucide-react";

import {
  acceptMemorySuggestion,
  createMemory,
  generateMemorySuggestionsFromText,
  getMemories,
  getMemorySuggestions,
  rejectMemorySuggestion,
  searchMemories,
  updateMemory,
  updateMemoryStatus,
} from "../api/memory.api";
import { getProjects } from "../api/projects.api";
import type { MemoryItem, MemorySearchItem, MemoryStatus, MemoryStatusFilter, MemorySuggestion, MemoryType, ProjectItem } from "../types/api";
import { formatDate } from "../utils/formatDate";
import { formatCount, labelMemoryStatus, labelMemoryType } from "../utils/labels";

const PAGE_SIZE = 10;
const MEMORY_TYPES: MemoryType[] = ["note", "requirement", "decision", "rule"];

type BusyAction = "load" | "save" | "search" | "textSuggestion" | `status:${string}` | `suggestion:${string}` | null;

interface MemoryFormState {
  projectId: string;
  type: MemoryType;
  title: string;
  content: string;
  occurredAt: string;
}

const emptyForm: MemoryFormState = {
  projectId: "",
  type: "note",
  title: "",
  content: "",
  occurredAt: "",
};

function toDateTimeLocal(value: string | null) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function toIsoOrNull(value: string) {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date.toISOString();
}

function suggestionSourceLabel(suggestion: MemorySuggestion) {
  if (suggestion.source_type === "chat_suggestion") {
    return suggestion.conversation_id ? `对话 ${suggestion.conversation_id}` : "对话";
  }
  if (suggestion.source_type === "document_suggestion") {
    return suggestion.source_ref ? `资料 ${suggestion.source_ref}` : "资料";
  }
  if (suggestion.source_type === "text_suggestion") {
    return suggestion.source_ref ? `文字 ${suggestion.source_ref}` : "文字";
  }
  return suggestion.source_ref ? `${suggestion.source_type} ${suggestion.source_ref}` : suggestion.source_type;
}

export function MemoryPage() {
  const formRef = useRef<HTMLDivElement | null>(null);
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [suggestions, setSuggestions] = useState<MemorySuggestion[]>([]);
  const [suggestionTotal, setSuggestionTotal] = useState(0);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [projectFilter, setProjectFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState<"" | MemoryType>("");
  const [statusFilter, setStatusFilter] = useState<MemoryStatusFilter>("active");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchProjectId, setSearchProjectId] = useState("");
  const [searchType, setSearchType] = useState<"" | MemoryType>("");
  const [searchIncludeArchived, setSearchIncludeArchived] = useState(false);
  const [searchLimit, setSearchLimit] = useState(5);
  const [searchResults, setSearchResults] = useState<MemorySearchItem[]>([]);
  const [suggestionTitle, setSuggestionTitle] = useState("");
  const [suggestionProjectId, setSuggestionProjectId] = useState("");
  const [suggestionText, setSuggestionText] = useState("");
  const [suggestionIncludeMemory, setSuggestionIncludeMemory] = useState(true);
  const [suggestionLimit, setSuggestionLimit] = useState(5);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<MemoryFormState>(emptyForm);
  const [busy, setBusy] = useState<BusyAction>("load");
  const [message, setMessage] = useState<string | null>(null);

  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const loadProjects = async () => {
    const response = await getProjects();
    setProjects(response.data);
  };

  const loadMemories = async (nextOffset = offset) => {
    const response = await getMemories({
      limit: PAGE_SIZE,
      offset: nextOffset,
      projectId: projectFilter || undefined,
      type: typeFilter || undefined,
      status: statusFilter,
    });
    setMemories(response.data.items);
    setTotal(response.data.total);
  };

  const loadSuggestions = async () => {
    const response = await getMemorySuggestions({ limit: 20, offset: 0, status: "pending" });
    setSuggestions(response.data.items);
    setSuggestionTotal(response.data.total);
  };

  const refresh = async (nextOffset = offset) => {
    setBusy("load");
    try {
      await Promise.all([loadProjects(), loadMemories(nextOffset), loadSuggestions()]);
      setMessage(null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "记忆加载失败");
    } finally {
      setBusy(null);
    }
  };

  const resetForm = () => {
    setEditingId(null);
    setForm(emptyForm);
  };

  const editMemory = (memory: MemoryItem) => {
    setEditingId(memory.id);
    setForm({
      projectId: memory.project_id ?? "",
      type: memory.type,
      title: memory.title,
      content: memory.content,
      occurredAt: toDateTimeLocal(memory.occurred_at),
    });
    setMessage(null);
    formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const saveMemory = async () => {
    if (busy !== null) {
      return;
    }
    setBusy("save");
    setMessage(null);
    try {
      const payload = {
        project_id: form.projectId || null,
        type: form.type,
        title: form.title,
        content: form.content,
        occurred_at: toIsoOrNull(form.occurredAt),
      };
      if (editingId) {
        await updateMemory(editingId, payload);
        await loadMemories(offset);
        setMessage("记忆已更新");
      } else {
        await createMemory(payload);
        setOffset(0);
        await loadMemories(0);
        setMessage("记忆已创建");
      }
      resetForm();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    } finally {
      setBusy(null);
    }
  };

  const toggleStatus = async (memory: MemoryItem) => {
    if (busy !== null) {
      return;
    }
    const nextStatus: MemoryStatus = memory.status === "archived" ? "active" : "archived";
    setBusy(`status:${memory.id}`);
    setMessage(null);
    try {
      await updateMemoryStatus(memory.id, nextStatus);
      const shouldStepBack = memories.length === 1 && offset > 0;
      const nextOffset = shouldStepBack ? Math.max(0, offset - PAGE_SIZE) : offset;
      if (nextOffset !== offset) {
        setOffset(nextOffset);
      }
      await loadMemories(nextOffset);
      setMessage(nextStatus === "archived" ? "记忆已归档" : "记忆已恢复");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "状态更新失败");
    } finally {
      setBusy(null);
    }
  };

  const runSearch = async () => {
    if (busy !== null || !searchQuery.trim()) {
      return;
    }
    setBusy("search");
    setMessage(null);
    try {
      const response = await searchMemories({
        query: searchQuery,
        limit: searchLimit,
        project_id: searchProjectId || null,
        types: searchType ? [searchType] : undefined,
        include_archived: searchIncludeArchived,
      });
      setSearchResults(response.data.items);
      setMessage(null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "记忆搜索失败");
    } finally {
      setBusy(null);
    }
  };

  const acceptSuggestion = async (suggestion: MemorySuggestion) => {
    if (busy !== null) {
      return;
    }
    setBusy(`suggestion:${suggestion.id}`);
    setMessage(null);
    try {
      await acceptMemorySuggestion(suggestion.id);
      await Promise.all([loadSuggestions(), loadMemories(offset)]);
      setMessage("建议已写入启用状态的记忆");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "接受建议失败");
    } finally {
      setBusy(null);
    }
  };

  const rejectSuggestion = async (suggestion: MemorySuggestion) => {
    if (busy !== null) {
      return;
    }
    setBusy(`suggestion:${suggestion.id}`);
    setMessage(null);
    try {
      await rejectMemorySuggestion(suggestion.id);
      await loadSuggestions();
      setMessage("建议已拒绝");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "拒绝建议失败");
    } finally {
      setBusy(null);
    }
  };

  const generateFromText = async () => {
    const cleanText = suggestionText.trim();
    if (busy !== null || !cleanText) {
      setMessage("请输入文字内容");
      return;
    }
    setBusy("textSuggestion");
    setMessage(null);
    try {
      const response = await generateMemorySuggestionsFromText({
        title: suggestionTitle.trim() || null,
        content: cleanText,
        project_id: suggestionProjectId || null,
        limit: suggestionLimit,
        include_memory: suggestionIncludeMemory,
      });
      await loadSuggestions();
      setSuggestionText("");
      setMessage(`已生成 ${response.data.total} 条待审核工作建议`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "文字建议生成失败");
    } finally {
      setBusy(null);
    }
  };

  useEffect(() => {
    void refresh(offset);
  }, [offset, projectFilter, typeFilter, statusFilter]);

  return (
    <section className="page">
      <header className="page-header row-header">
        <div>
          <p className="eyebrow">长期记忆</p>
          <h1>记忆</h1>
        </div>
        <button className="icon-button" type="button" onClick={() => void refresh()} title="刷新记忆" disabled={busy !== null}>
          <RefreshCw size={18} />
        </button>
      </header>

      <section className="table-panel">
        <div className="table-heading">
          <strong>待审核建议</strong>
          <span>{busy === "load" ? "加载中" : `${suggestionTotal} 条待审核`}</span>
        </div>
        {suggestions.length === 0 ? (
          <div className="empty-panel compact">暂无待审核建议</div>
        ) : (
          <div className="source-grid compact suggestion-grid">
            {suggestions.map((suggestion) => {
              const suggestionBusy = busy === `suggestion:${suggestion.id}`;
              return (
                <article className="source-card" key={suggestion.id}>
                  <div className="source-card-header">
                    <strong>{labelMemoryType(suggestion.type)}</strong>
                    <span>{formatDate(suggestion.created_at)}</span>
                  </div>
                  <h2>{suggestion.title}</h2>
                  <dl>
                    <dt>项目</dt>
                    <dd>{suggestion.project_name ?? "未归档"}</dd>
                    <dt>来源</dt>
                    <dd>{suggestionSourceLabel(suggestion)}</dd>
                  </dl>
                  <p>{suggestion.content}</p>
                  {suggestion.rationale ? <p>{suggestion.rationale}</p> : null}
                  <div className="action-group">
                    <button className="secondary-button" type="button" onClick={() => void acceptSuggestion(suggestion)} disabled={busy !== null}>
                      <CheckCircle2 size={16} />
                      <span>{suggestionBusy ? "处理中" : "接受"}</span>
                    </button>
                    <button className="secondary-button danger" type="button" onClick={() => void rejectSuggestion(suggestion)} disabled={busy !== null}>
                      <XCircle size={16} />
                      <span>拒绝</span>
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>

      <div className="memory-form">
        <label>
          <span>建议项目</span>
          <select value={suggestionProjectId} onChange={(event) => setSuggestionProjectId(event.target.value)} disabled={busy !== null}>
            <option value="">未归档</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>结合记忆</span>
          <select value={suggestionIncludeMemory ? "on" : "off"} onChange={(event) => setSuggestionIncludeMemory(event.target.value === "on")} disabled={busy !== null}>
            <option value="on">开启</option>
            <option value="off">关闭</option>
          </select>
        </label>
        <label>
          <span>数量</span>
          <input type="number" min={1} max={10} value={suggestionLimit} onChange={(event) => setSuggestionLimit(Number(event.target.value))} disabled={busy !== null} />
        </label>
        <label className="memory-title">
          <span>建议标题</span>
          <input value={suggestionTitle} onChange={(event) => setSuggestionTitle(event.target.value)} disabled={busy !== null} />
        </label>
        <label className="memory-content">
          <span>文字</span>
          <textarea value={suggestionText} onChange={(event) => setSuggestionText(event.target.value)} disabled={busy !== null} />
        </label>
        <div className="memory-form-actions">
          <button className="secondary-button" type="button" onClick={() => void generateFromText()} disabled={busy !== null || !suggestionText.trim()}>
            <Lightbulb size={16} />
            <span>{busy === "textSuggestion" ? "生成中" : "生成建议"}</span>
          </button>
        </div>
      </div>

      <div className="memory-form" ref={formRef}>
        <label>
          <span>类型</span>
          <select value={form.type} onChange={(event) => setForm((current) => ({ ...current, type: event.target.value as MemoryType }))} disabled={busy !== null}>
            {MEMORY_TYPES.map((type) => (
              <option key={type} value={type}>
                {labelMemoryType(type)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>项目</span>
          <select value={form.projectId} onChange={(event) => setForm((current) => ({ ...current, projectId: event.target.value }))} disabled={busy !== null}>
            <option value="">未归档</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>发生时间</span>
          <input
            type="datetime-local"
            value={form.occurredAt}
            onChange={(event) => setForm((current) => ({ ...current, occurredAt: event.target.value }))}
            disabled={busy !== null}
          />
        </label>
        <label className="memory-title">
          <span>标题</span>
          <input value={form.title} onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))} disabled={busy !== null} />
        </label>
        <label className="memory-content">
          <span>内容</span>
          <textarea value={form.content} onChange={(event) => setForm((current) => ({ ...current, content: event.target.value }))} disabled={busy !== null} />
        </label>
        <div className="memory-form-actions">
          {editingId ? (
            <button className="secondary-button" type="button" onClick={resetForm} disabled={busy !== null}>
              <X size={16} />
              <span>取消</span>
            </button>
          ) : null}
          <button className="secondary-button" type="button" onClick={() => void saveMemory()} disabled={busy !== null || !form.title.trim() || !form.content.trim()}>
            <Save size={16} />
            <span>{busy === "save" ? "保存中" : editingId ? "更新" : "创建"}</span>
          </button>
        </div>
      </div>

      <div className="retrieval-panel">
        <label className="retrieval-query">
          <span>搜索</span>
          <input value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} disabled={busy !== null} />
        </label>
        <label>
          <span>项目</span>
          <select value={searchProjectId} onChange={(event) => setSearchProjectId(event.target.value)} disabled={busy !== null}>
            <option value="">全部项目</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>类型</span>
          <select value={searchType} onChange={(event) => setSearchType(event.target.value as "" | MemoryType)} disabled={busy !== null}>
            <option value="">全部类型</option>
            {MEMORY_TYPES.map((type) => (
              <option key={type} value={type}>
                {labelMemoryType(type)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>归档</span>
          <select value={searchIncludeArchived ? "include" : "exclude"} onChange={(event) => setSearchIncludeArchived(event.target.value === "include")} disabled={busy !== null}>
            <option value="exclude">排除</option>
            <option value="include">包含</option>
          </select>
        </label>
        <label>
          <span>数量</span>
          <input type="number" min={1} max={20} value={searchLimit} onChange={(event) => setSearchLimit(Number(event.target.value))} disabled={busy !== null} />
        </label>
        <button className="secondary-button retrieval-button" type="button" onClick={() => void runSearch()} disabled={busy !== null || !searchQuery.trim()}>
          <Search size={16} />
          <span>{busy === "search" ? "搜索中" : "搜索"}</span>
        </button>
      </div>

      {searchResults.length > 0 ? (
        <div className="source-grid compact">
          {searchResults.map((item) => (
            <article className="source-card" key={`${item.rank}:${item.memory.id}`}>
              <div className="source-card-header">
                <strong>#{item.rank}</strong>
                <span>{item.matched_fields.join(", ")}</span>
              </div>
              <h2>{item.memory.title}</h2>
              <dl>
                <dt>类型</dt>
                <dd>{labelMemoryType(item.memory.type)}</dd>
                <dt>项目</dt>
                <dd>{item.memory.project_name ?? "未归档"}</dd>
                <dt>分数</dt>
                <dd>{item.score.toFixed(2)}</dd>
              </dl>
              <p>{item.memory.content}</p>
            </article>
          ))}
        </div>
      ) : null}

      <div className="filters-row">
        <label>
          <span>项目</span>
          <select
            value={projectFilter}
            onChange={(event) => {
              setProjectFilter(event.target.value);
              setOffset(0);
            }}
            disabled={busy !== null}
          >
            <option value="">全部项目</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>类型</span>
          <select
            value={typeFilter}
            onChange={(event) => {
              setTypeFilter(event.target.value as "" | MemoryType);
              setOffset(0);
            }}
            disabled={busy !== null}
          >
            <option value="">全部类型</option>
            {MEMORY_TYPES.map((type) => (
              <option key={type} value={type}>
                {labelMemoryType(type)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>状态</span>
          <select
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value as MemoryStatusFilter);
              setOffset(0);
            }}
            disabled={busy !== null}
          >
            <option value="active">启用</option>
            <option value="archived">已归档</option>
            <option value="all">全部</option>
          </select>
        </label>
      </div>

      {message ? <div className="inline-message">{message}</div> : null}

      <div className="table-panel">
        <div className="table-heading">
          <strong>结构化记忆</strong>
          <span>{busy === "load" ? "加载中" : formatCount(total)}</span>
        </div>
        {memories.length === 0 ? (
          <div className="empty-panel compact">{busy === "load" ? "正在加载记忆" : "没有找到记忆"}</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>记忆</th>
                <th>类型</th>
                <th>项目</th>
                <th>状态</th>
                <th>时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {memories.map((memory) => {
                const statusBusy = busy === `status:${memory.id}`;
                return (
                  <tr key={memory.id}>
                    <td>
                      <strong>{memory.title}</strong>
                      <span>{memory.content}</span>
                    </td>
                    <td>{labelMemoryType(memory.type)}</td>
                    <td>{memory.project_name ?? "未归档"}</td>
                    <td>{labelMemoryStatus(memory.status)}</td>
                    <td>
                      <strong>{memory.occurred_at ? formatDate(memory.occurred_at) : formatDate(memory.created_at)}</strong>
                      <span>创建于 {formatDate(memory.created_at)}</span>
                    </td>
                    <td>
                      <div className="action-group">
                        <button className="secondary-button" type="button" onClick={() => editMemory(memory)} disabled={busy !== null}>
                          编辑
                        </button>
                        <button
                          className="icon-button small"
                          type="button"
                          title={memory.status === "archived" ? "恢复记忆" : "归档记忆"}
                          onClick={() => void toggleStatus(memory)}
                          disabled={busy !== null}
                        >
                          {memory.status === "archived" ? <RotateCcw size={16} /> : <Archive size={16} />}
                        </button>
                      </div>
                      {statusBusy ? <span>更新中</span> : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <div className="pagination-row">
          <button className="secondary-button" type="button" disabled={offset === 0 || busy !== null} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
            上一页
          </button>
          <span>
            第 {page} / {totalPages} 页
          </span>
          <button className="secondary-button" type="button" disabled={offset + PAGE_SIZE >= total || busy !== null} onClick={() => setOffset(offset + PAGE_SIZE)}>
            下一页
          </button>
        </div>
      </div>
    </section>
  );
}
