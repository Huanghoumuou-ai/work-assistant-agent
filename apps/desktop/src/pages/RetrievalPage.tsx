import { useEffect, useMemo, useState } from "react";
import { RefreshCw, Search } from "lucide-react";

import { getProjects } from "../api/projects.api";
import { searchRetrieval } from "../api/retrieval.api";
import type { ProjectItem, RetrievalSearchResult } from "../types/api";

const DEFAULT_TOP_K = 5;

export function RetrievalPage() {
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(DEFAULT_TOP_K);
  const [projectId, setProjectId] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [searching, setSearching] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [result, setResult] = useState<RetrievalSearchResult | null>(null);

  const projectNameById = useMemo(() => {
    return new Map(projects.map((project) => [project.id, project.name]));
  }, [projects]);

  const loadProjects = async () => {
    setLoadingProjects(true);
    try {
      const response = await getProjects();
      setProjects(response.data);
      setMessage(null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to load projects");
    } finally {
      setLoadingProjects(false);
    }
  };

  const runSearch = async () => {
    const cleanQuery = query.trim();
    if (!cleanQuery || searching) {
      setMessage("Query is required");
      return;
    }

    setSearching(true);
    setMessage(null);
    try {
      const response = await searchRetrieval({
        query: cleanQuery,
        top_k: topK,
        project_id: projectId || null,
        document_id: documentId.trim() || null,
      });
      setResult(response.data);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Retrieval failed");
    } finally {
      setSearching(false);
    }
  };

  useEffect(() => {
    void loadProjects();
  }, []);

  return (
    <section className="page">
      <header className="page-header row-header">
        <div>
          <p className="eyebrow">Phase 7</p>
          <h1>Retrieval</h1>
        </div>
        <button className="icon-button" type="button" onClick={() => void loadProjects()} title="Refresh projects" disabled={searching}>
          <RefreshCw size={18} />
        </button>
      </header>

      <div className="retrieval-panel">
        <label className="retrieval-query">
          <span>Query</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                void runSearch();
              }
            }}
            placeholder="Search indexed chunks"
            disabled={searching}
          />
        </label>
        <label>
          <span>Top K</span>
          <input
            type="number"
            min={1}
            max={20}
            value={topK}
            onChange={(event) => setTopK(Number(event.target.value))}
            disabled={searching}
          />
        </label>
        <label>
          <span>Project</span>
          <select value={projectId} onChange={(event) => setProjectId(event.target.value)} disabled={searching || loadingProjects}>
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
          <input value={documentId} onChange={(event) => setDocumentId(event.target.value)} placeholder="Optional exact document id" disabled={searching} />
        </label>
        <button className="secondary-button retrieval-button" type="button" onClick={() => void runSearch()} disabled={searching || !query.trim()}>
          <Search size={16} />
          <span>{searching ? "Searching" : "Search"}</span>
        </button>
      </div>

      {message ? <div className="inline-message">{message}</div> : null}

      <div className="table-panel">
        <div className="table-heading">
          <strong>Source Metadata</strong>
          <span>{result ? `${result.items.length} results for "${result.query}"` : "No search yet"}</span>
        </div>
        {!result ? (
          <div className="empty-panel compact">Run retrieval against indexed chunks. Results omit chunk content and vectors.</div>
        ) : result.items.length === 0 ? (
          <div className="empty-panel compact">No uploaded indexed source matched the query.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Rank</th>
                <th>Source</th>
                <th>Chunk</th>
                <th>Score</th>
                <th>Provider</th>
                <th>Hashes</th>
              </tr>
            </thead>
            <tbody>
              {result.items.map((item) => (
                <tr key={`${item.document_id}:${item.chunk_id}`}>
                  <td>{item.rank}</td>
                  <td>
                    <strong>{item.source_filename}</strong>
                    <span>{item.project_id ? projectNameById.get(item.project_id) ?? item.project_id : "Unfiled"}</span>
                    <span>{item.document_id}</span>
                  </td>
                  <td>
                    <strong>#{item.chunk_index}</strong>
                    <span>
                      chars {item.char_start}-{item.char_end}
                    </span>
                    <span>{item.chunk_id}</span>
                  </td>
                  <td>
                    <strong>{item.score.toFixed(4)}</strong>
                    <span>distance {item.distance.toFixed(4)}</span>
                  </td>
                  <td>
                    <strong>{item.provider}</strong>
                    <span>{item.model}</span>
                  </td>
                  <td>
                    <span>chunk {item.content_sha256.slice(0, 12)}</span>
                    <span>parse {item.parse_content_sha256.slice(0, 12)}</span>
                    <span>set {item.chunk_set_sha256.slice(0, 12)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
