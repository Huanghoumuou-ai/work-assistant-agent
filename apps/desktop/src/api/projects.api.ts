import { getJson, postJson } from "./client";
import type { ApiResponse, ProjectItem } from "../types/api";

export function getProjects() {
  return getJson<ApiResponse<ProjectItem[]>>("/api/projects");
}

export function createProject(payload: { name: string; description?: string | null }) {
  return postJson<ApiResponse<ProjectItem>>("/api/projects", payload);
}
