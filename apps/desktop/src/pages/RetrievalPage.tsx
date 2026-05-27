import { useEffect, useMemo, useState } from "react";
import { RefreshCw, Search } from "lucide-react";

import { getProjects } from "../api/projects.api";
import { searchRetrieval } from "../api/retrieval.api";
import type { ProjectItem, RetrievalSearchResult } from "../types/api";
import { formatCount } from "../utils/labels";

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
      setMessage(error instanceof Error ? error.message : "项目加载失败");
    } finally {
      setLoadingProjects(false);
    }
  };

  const runSearch = async () => {
    const cleanQuery = query.trim();
    if (!cleanQuery || searching) {
      setMessage("请输入检索内容");
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
      setMessage(error instanceof Error ? error.message : "检索失败");
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
          <p className="eyebrow">检索调试</p>
          <h1>检索</h1>
        </div>
        <button className="icon-button" type="button" onClick={() => void loadProjects()} title="刷新项目" disabled={searching}>
          <RefreshCw size={18} />
        </button>
      </header>

      <div className="retrieval-panel">
        <label className="retrieval-query">
          <span>查询</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                void runSearch();
              }
            }}
            placeholder="搜索已索引的切块"
            disabled={searching}
          />
        </label>
        <label>
          <span>返回数量</span>
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
          <span>项目</span>
          <select value={projectId} onChange={(event) => setProjectId(event.target.value)} disabled={searching || loadingProjects}>
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
          <input value={documentId} onChange={(event) => setDocumentId(event.target.value)} placeholder="可选，精确资料 ID" disabled={searching} />
        </label>
        <button className="secondary-button retrieval-button" type="button" onClick={() => void runSearch()} disabled={searching || !query.trim()}>
          <Search size={16} />
          <span>{searching ? "检索中" : "检索"}</span>
        </button>
      </div>

      {message ? <div className="inline-message">{message}</div> : null}

      <div className="table-panel">
        <div className="table-heading">
          <strong>来源元数据</strong>
          <span>{result ? `${formatCount(result.items.length, "条")}，查询：“${result.query}”` : "尚未检索"}</span>
        </div>
        {!result ? (
          <div className="empty-panel compact">对已索引切块执行检索。结果不展示切块正文和向量。</div>
        ) : result.items.length === 0 ? (
          <div className="empty-panel compact">没有匹配的已上传索引来源。</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>排名</th>
                <th>来源</th>
                <th>切块</th>
                <th>分数</th>
                <th>服务商</th>
                <th>哈希</th>
              </tr>
            </thead>
            <tbody>
              {result.items.map((item) => (
                <tr key={`${item.document_id}:${item.chunk_id}`}>
                  <td>{item.rank}</td>
                  <td>
                    <strong>{item.source_filename}</strong>
                    <span>{item.project_id ? projectNameById.get(item.project_id) ?? item.project_id : "未归档"}</span>
                    <span>{item.document_id}</span>
                  </td>
                  <td>
                    <strong>#{item.chunk_index}</strong>
                    <span>
                      字符 {item.char_start}-{item.char_end}
                    </span>
                    <span>{item.chunk_id}</span>
                  </td>
                  <td>
                    <strong>{item.score.toFixed(4)}</strong>
                    <span>距离 {item.distance.toFixed(4)}</span>
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
