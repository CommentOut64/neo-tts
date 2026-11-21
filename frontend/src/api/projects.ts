import axios from "./http";
import type {
  ProjectActionResponse,
  ProjectCaptureToken,
  ProjectPayload,
} from "@/types/projects";

export async function createProject(input: {
  project_id?: string;
  workspace_id?: string;
} = {}): Promise<ProjectActionResponse> {
  const { data } = await axios.post<ProjectActionResponse>("/v1/projects/new", input);
  return data;
}

export async function openProject(path: string): Promise<ProjectActionResponse> {
  const { data } = await axios.post<ProjectActionResponse>("/v1/projects/open", { path });
  return data;
}

export async function saveProject(
  payload: ProjectPayload,
  token?: ProjectCaptureToken,
): Promise<ProjectActionResponse> {
  const { data } = await axios.post<ProjectActionResponse>("/v1/projects/save", {
    payload,
    ...(token ? { token } : {}),
  });
  return data;
}

export async function saveProjectAs(
  payload: ProjectPayload,
  target: string,
  token?: ProjectCaptureToken,
): Promise<ProjectActionResponse> {
  const { data } = await axios.post<ProjectActionResponse>("/v1/projects/save-as", {
    payload,
    target,
    ...(token ? { token } : {}),
  });
  return data;
}

export async function importLegacyProject(
  path: string,
  projectId?: string,
): Promise<ProjectActionResponse> {
  const { data } = await axios.post<ProjectActionResponse>("/v1/projects/import-legacy", {
    path,
    ...(projectId ? { project_id: projectId } : {}),
  });
  return data;
}

export async function getProjectState(): Promise<ProjectActionResponse> {
  const { data } = await axios.get<ProjectActionResponse>("/v1/projects/state");
  return data;
}
