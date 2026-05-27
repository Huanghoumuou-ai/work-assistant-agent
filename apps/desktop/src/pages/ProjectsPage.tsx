import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Plus, RefreshCw } from "lucide-react";

import { createProject, getProjects } from "../api/projects.api";
import type { ProjectItem } from "../types/api";
import { formatDate } from "../utils/formatDate";

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
      setMessage(error instanceof Error ? error.message : "Failed to load projects");
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
      setMessage("Project created");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Project creation failed");
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
          <p className="eyebrow">Phase 3</p>
          <h1>Projects</h1>
        </div>
        <button className="icon-button" type="button" onClick={() => void loadProjects()} title="Refresh projects" disabled={loading || creating}>
          <RefreshCw size={18} />
        </button>
      </header>

      <form className="form-panel" onSubmit={(event) => void submit(event)}>
        <label>
          <span>Name</span>
          <input value={name} maxLength={100} onChange={(event) => setName(event.target.value)} disabled={creating} />
        </label>
        <label>
          <span>Description</span>
          <textarea value={description} maxLength={1000} onChange={(event) => setDescription(event.target.value)} disabled={creating} />
        </label>
        <button className="secondary-button" type="submit" disabled={creating}>
          <Plus size={16} />
          {creating ? "Creating" : "Create Project"}
        </button>
      </form>

      {message ? <div className="inline-message">{message}</div> : null}

      <div className="table-panel">
        <div className="table-heading">
          <strong>Projects</strong>
          <span>{loading ? "Loading" : `${projects.length} total`}</span>
        </div>
        {projects.length === 0 ? (
          <div className="empty-panel compact">{loading ? "Loading projects" : "No projects yet"}</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Description</th>
                <th>Created</th>
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
