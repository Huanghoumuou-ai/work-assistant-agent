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
    return suggestion.conversation_id ? `Chat ${suggestion.conversation_id}` : "Chat";
  }
  if (suggestion.source_type === "document_suggestion") {
    return suggestion.source_ref ? `Document ${suggestion.source_ref}` : "Document";
  }
  if (suggestion.source_type === "text_suggestion") {
    return suggestion.source_ref ? `Text ${suggestion.source_ref}` : "Text";
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
      setMessage(error instanceof Error ? error.message : "Failed to load memories");
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
        setMessage("Memory updated");
      } else {
        await createMemory(payload);
        setOffset(0);
        await loadMemories(0);
        setMessage("Memory created");
      }
      resetForm();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Save failed");
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
      setMessage(nextStatus === "archived" ? "Memory archived" : "Memory restored");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Status update failed");
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
      setMessage(error instanceof Error ? error.message : "Memory search failed");
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
      setMessage("Suggestion accepted into active Memory");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Accept suggestion failed");
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
      setMessage("Suggestion rejected");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Reject suggestion failed");
    } finally {
      setBusy(null);
    }
  };

  const generateFromText = async () => {
    const cleanText = suggestionText.trim();
    if (busy !== null || !cleanText) {
      setMessage("Text content is required");
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
      setMessage(`Generated ${response.data.total} pending work suggestion${response.data.total === 1 ? "" : "s"} for review`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Text suggestion generation failed");
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
          <p className="eyebrow">Phase 11</p>
          <h1>Memory</h1>
        </div>
        <button className="icon-button" type="button" onClick={() => void refresh()} title="Refresh memories" disabled={busy !== null}>
          <RefreshCw size={18} />
        </button>
      </header>

      <section className="table-panel">
        <div className="table-heading">
          <strong>Pending Suggestions</strong>
          <span>{busy === "load" ? "Loading" : `${suggestionTotal} pending`}</span>
        </div>
        {suggestions.length === 0 ? (
          <div className="empty-panel compact">No pending suggestions</div>
        ) : (
          <div className="source-grid compact suggestion-grid">
            {suggestions.map((suggestion) => {
              const suggestionBusy = busy === `suggestion:${suggestion.id}`;
              return (
                <article className="source-card" key={suggestion.id}>
                  <div className="source-card-header">
                    <strong>{suggestion.type}</strong>
                    <span>{formatDate(suggestion.created_at)}</span>
                  </div>
                  <h2>{suggestion.title}</h2>
                  <dl>
                    <dt>Project</dt>
                    <dd>{suggestion.project_name ?? "Unfiled"}</dd>
                    <dt>Source</dt>
                    <dd>{suggestionSourceLabel(suggestion)}</dd>
                  </dl>
                  <p>{suggestion.content}</p>
                  {suggestion.rationale ? <p>{suggestion.rationale}</p> : null}
                  <div className="action-group">
                    <button className="secondary-button" type="button" onClick={() => void acceptSuggestion(suggestion)} disabled={busy !== null}>
                      <CheckCircle2 size={16} />
                      <span>{suggestionBusy ? "Reviewing" : "Accept"}</span>
                    </button>
                    <button className="secondary-button danger" type="button" onClick={() => void rejectSuggestion(suggestion)} disabled={busy !== null}>
                      <XCircle size={16} />
                      <span>Reject</span>
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
          <span>Suggestion Project</span>
          <select value={suggestionProjectId} onChange={(event) => setSuggestionProjectId(event.target.value)} disabled={busy !== null}>
            <option value="">Unfiled</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Include Memory</span>
          <select value={suggestionIncludeMemory ? "on" : "off"} onChange={(event) => setSuggestionIncludeMemory(event.target.value === "on")} disabled={busy !== null}>
            <option value="on">On</option>
            <option value="off">Off</option>
          </select>
        </label>
        <label>
          <span>Limit</span>
          <input type="number" min={1} max={10} value={suggestionLimit} onChange={(event) => setSuggestionLimit(Number(event.target.value))} disabled={busy !== null} />
        </label>
        <label className="memory-title">
          <span>Suggestion Title</span>
          <input value={suggestionTitle} onChange={(event) => setSuggestionTitle(event.target.value)} disabled={busy !== null} />
        </label>
        <label className="memory-content">
          <span>Text</span>
          <textarea value={suggestionText} onChange={(event) => setSuggestionText(event.target.value)} disabled={busy !== null} />
        </label>
        <div className="memory-form-actions">
          <button className="secondary-button" type="button" onClick={() => void generateFromText()} disabled={busy !== null || !suggestionText.trim()}>
            <Lightbulb size={16} />
            <span>{busy === "textSuggestion" ? "Generating" : "Generate Suggestions"}</span>
          </button>
        </div>
      </div>

      <div className="memory-form" ref={formRef}>
        <label>
          <span>Type</span>
          <select value={form.type} onChange={(event) => setForm((current) => ({ ...current, type: event.target.value as MemoryType }))} disabled={busy !== null}>
            {MEMORY_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Project</span>
          <select value={form.projectId} onChange={(event) => setForm((current) => ({ ...current, projectId: event.target.value }))} disabled={busy !== null}>
            <option value="">Unfiled</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Occurred At</span>
          <input
            type="datetime-local"
            value={form.occurredAt}
            onChange={(event) => setForm((current) => ({ ...current, occurredAt: event.target.value }))}
            disabled={busy !== null}
          />
        </label>
        <label className="memory-title">
          <span>Title</span>
          <input value={form.title} onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))} disabled={busy !== null} />
        </label>
        <label className="memory-content">
          <span>Content</span>
          <textarea value={form.content} onChange={(event) => setForm((current) => ({ ...current, content: event.target.value }))} disabled={busy !== null} />
        </label>
        <div className="memory-form-actions">
          {editingId ? (
            <button className="secondary-button" type="button" onClick={resetForm} disabled={busy !== null}>
              <X size={16} />
              <span>Cancel</span>
            </button>
          ) : null}
          <button className="secondary-button" type="button" onClick={() => void saveMemory()} disabled={busy !== null || !form.title.trim() || !form.content.trim()}>
            <Save size={16} />
            <span>{busy === "save" ? "Saving" : editingId ? "Update" : "Create"}</span>
          </button>
        </div>
      </div>

      <div className="retrieval-panel">
        <label className="retrieval-query">
          <span>Search</span>
          <input value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} disabled={busy !== null} />
        </label>
        <label>
          <span>Project</span>
          <select value={searchProjectId} onChange={(event) => setSearchProjectId(event.target.value)} disabled={busy !== null}>
            <option value="">All projects</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Type</span>
          <select value={searchType} onChange={(event) => setSearchType(event.target.value as "" | MemoryType)} disabled={busy !== null}>
            <option value="">All types</option>
            {MEMORY_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Archived</span>
          <select value={searchIncludeArchived ? "include" : "exclude"} onChange={(event) => setSearchIncludeArchived(event.target.value === "include")} disabled={busy !== null}>
            <option value="exclude">Exclude</option>
            <option value="include">Include</option>
          </select>
        </label>
        <label>
          <span>Limit</span>
          <input type="number" min={1} max={20} value={searchLimit} onChange={(event) => setSearchLimit(Number(event.target.value))} disabled={busy !== null} />
        </label>
        <button className="secondary-button retrieval-button" type="button" onClick={() => void runSearch()} disabled={busy !== null || !searchQuery.trim()}>
          <Search size={16} />
          <span>{busy === "search" ? "Searching" : "Search"}</span>
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
                <dt>Type</dt>
                <dd>{item.memory.type}</dd>
                <dt>Project</dt>
                <dd>{item.memory.project_name ?? "Unfiled"}</dd>
                <dt>Score</dt>
                <dd>{item.score.toFixed(2)}</dd>
              </dl>
              <p>{item.memory.content}</p>
            </article>
          ))}
        </div>
      ) : null}

      <div className="filters-row">
        <label>
          <span>Project</span>
          <select
            value={projectFilter}
            onChange={(event) => {
              setProjectFilter(event.target.value);
              setOffset(0);
            }}
            disabled={busy !== null}
          >
            <option value="">All projects</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Type</span>
          <select
            value={typeFilter}
            onChange={(event) => {
              setTypeFilter(event.target.value as "" | MemoryType);
              setOffset(0);
            }}
            disabled={busy !== null}
          >
            <option value="">All types</option>
            {MEMORY_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Status</span>
          <select
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value as MemoryStatusFilter);
              setOffset(0);
            }}
            disabled={busy !== null}
          >
            <option value="active">Active</option>
            <option value="archived">Archived</option>
            <option value="all">All</option>
          </select>
        </label>
      </div>

      {message ? <div className="inline-message">{message}</div> : null}

      <div className="table-panel">
        <div className="table-heading">
          <strong>Structured Memories</strong>
          <span>{busy === "load" ? "Loading" : `${total} total`}</span>
        </div>
        {memories.length === 0 ? (
          <div className="empty-panel compact">{busy === "load" ? "Loading memories" : "No memories found"}</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Memory</th>
                <th>Type</th>
                <th>Project</th>
                <th>Status</th>
                <th>When</th>
                <th>Actions</th>
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
                    <td>{memory.type}</td>
                    <td>{memory.project_name ?? "Unfiled"}</td>
                    <td>{memory.status}</td>
                    <td>
                      <strong>{memory.occurred_at ? formatDate(memory.occurred_at) : formatDate(memory.created_at)}</strong>
                      <span>created {formatDate(memory.created_at)}</span>
                    </td>
                    <td>
                      <div className="action-group">
                        <button className="secondary-button" type="button" onClick={() => editMemory(memory)} disabled={busy !== null}>
                          Edit
                        </button>
                        <button
                          className="icon-button small"
                          type="button"
                          title={memory.status === "archived" ? "Restore memory" : "Archive memory"}
                          onClick={() => void toggleStatus(memory)}
                          disabled={busy !== null}
                        >
                          {memory.status === "archived" ? <RotateCcw size={16} /> : <Archive size={16} />}
                        </button>
                      </div>
                      {statusBusy ? <span>Updating</span> : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <div className="pagination-row">
          <button className="secondary-button" type="button" disabled={offset === 0 || busy !== null} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
            Previous
          </button>
          <span>
            Page {page} of {totalPages}
          </span>
          <button className="secondary-button" type="button" disabled={offset + PAGE_SIZE >= total || busy !== null} onClick={() => setOffset(offset + PAGE_SIZE)}>
            Next
          </button>
        </div>
      </div>
    </section>
  );
}
