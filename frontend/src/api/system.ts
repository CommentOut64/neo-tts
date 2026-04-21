import axios from "./http";
import type { PrepareExitResponse } from "@/types/system";

export interface FolderSelectResponse {
  path: string | null;
}

export interface FileSelectResponse {
  path: string | null;
}

export async function openFolderDialog(
  initialDir?: string,
): Promise<string | null> {
  const { data } = await axios.get<FolderSelectResponse>(
    "/v1/system/dialog/folder",
    {
      params: { initial_dir: initialDir },
    },
  );
  return data.path;
}

export async function openFileDialog(
  accept: string,
  initialDir?: string,
): Promise<string | null> {
  const { data } = await axios.get<FileSelectResponse>(
    "/v1/system/dialog/file",
    {
      params: {
        initial_dir: initialDir,
        accept,
      },
    },
  );
  return data.path;
}

export async function prepareExit(): Promise<PrepareExitResponse> {
  const { data } = await axios.post<PrepareExitResponse>("/v1/system/prepare-exit");
  return data;
}

export interface SystemVersionInfo {
  version: string;
  build_date?: string;
}

export interface UpdateCheckResult {
  has_update: boolean;
  latest_version?: string;
  release_notes?: string;
  download_url?: string;
}

export async function getVersion(): Promise<SystemVersionInfo> {
  const { data } = await axios.get<SystemVersionInfo>("/v1/system/version");
  return data;
}

export async function checkUpdate(): Promise<UpdateCheckResult> {
  // Mock endpoint behavior
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({
        has_update: false,
        latest_version: "1.0.0-beta",
        release_notes: "Minor updates and fixes.",
        download_url: "https://github.com/CommentOut64/neo-tts/releases",
      });
    }, 1200);
  });
}
