import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Plus, RefreshCw } from "lucide-react";

import { createProject, getProjects } from "../api/projects.api";
import type { ProjectItem } from "../types/api";
import { formatDate } from "../utils/formatDate";
import { formatCount } from "../utils/labels";

export function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const loadProjects = async () => {
    setLoading(true);
    try {
      const response = await getProjects();
      setProjects(response.data);
      setMessage(null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "项目加载失败");
    } finally {
      setLoading(false);
    }
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (creating) {
      return;
    }

    setCreating(true);
    setMessage(null);
    try {
      await createProject({ name, description: description || null });
      setName("");
      setDescription("");
      await loadProjects();
      setMessage("项目已创建");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "项目创建失败");
    } finally {
      setCreating(false);
    }
  };

  useEffect(() => {
    void loadProjects();
  }, []);

  return (
    <section className="page">
      <header className="page-header row-header">
        <div>
          <p className="eyebrow">项目</p>
          <h1>项目</h1>
        </div>
        <button className="icon-button" type="button" onClick={() => void loadProjects()} title="刷新项目" disabled={loading || creating}>
          <RefreshCw size={18} />
        </button>
      </header>

      <form className="form-panel" onSubmit={(event) => void submit(event)}>
        <label>
          <span>名称</span>
          <input value={name} maxLength={100} onChange={(event) => setName(event.target.value)} disabled={creating} />
        </label>
        <label>
          <span>描述</span>
          <textarea value={description} maxLength={1000} onChange={(event) => setDescription(event.target.value)} disabled={creating} />
        </label>
        <button className="secondary-button" type="submit" disabled={creating}>
          <Plus size={16} />
          {creating ? "创建中" : "创建项目"}
        </button>
      </form>

      {message ? <div className="inline-message">{message}</div> : null}

      <div className="table-panel">
        <div className="table-heading">
          <strong>项目列表</strong>
          <span>{loading ? "加载中" : formatCount(projects.length)}</span>
        </div>
        {projects.length === 0 ? (
          <div className="empty-panel compact">{loading ? "正在加载项目" : "还没有项目"}</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>名称</th>
                <th>描述</th>
                <th>创建时间</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((project) => (
                <tr key={project.id}>
                  <td>
                    <strong>{project.name}</strong>
                    <span>{project.id}</span>
                  </td>
                  <td>{project.description ?? ""}</td>
                  <td>{formatDate(project.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
