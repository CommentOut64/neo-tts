import axios from "./http";
import type { PrepareExitResponse } from "@/types/system";
import type {
  AppUpdateCheckRequest,
  AppUpdateCheckResponse,
  AppUpdateDownloadRequest,
  AppUpdateDownloadResponse,
  AppUpdateRestartRequest,
  AppUpdateRestartResponse,
} from "@/types/update";

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

export async function getVersion(): Promise<SystemVersionInfo> {
  const { data } = await axios.get<SystemVersionInfo>("/v1/system/version");
  return data;
}

export async function checkForAppUpdate(
  request: AppUpdateCheckRequest,
): Promise<AppUpdateCheckResponse> {
  const bridge = getElectronUpdateBridge();
  if (!bridge) {
    return { status: "up-to-date" };
  }
  return bridge.checkForAppUpdate(request);
}

export async function startAppUpdateDownload(
  request: AppUpdateDownloadRequest,
): Promise<AppUpdateDownloadResponse> {
  const bridge = getElectronUpdateBridge();
  if (!bridge) {
    throw new Error("当前环境不支持下载桌面更新");
  }
  return bridge.startAppUpdateDownload(request);
}

export async function restartAndApplyAppUpdate(
  request: AppUpdateRestartRequest,
): Promise<AppUpdateRestartResponse> {
  const bridge = getElectronUpdateBridge();
  if (!bridge) {
    throw new Error("当前环境不支持应用桌面更新");
  }
  return bridge.restartAndApplyAppUpdate(request);
}

function getElectronUpdateBridge() {
  if (typeof window === "undefined") {
    return null;
  }

  const bridge = window.neoTTS;
  if (!bridge || bridge.runtime !== "electron") {
    return null;
  }
  if (typeof bridge.checkForAppUpdate !== "function") {
    return null;
  }
  if (typeof bridge.startAppUpdateDownload !== "function") {
    return null;
  }
  if (typeof bridge.restartAndApplyAppUpdate !== "function") {
    return null;
  }
  return bridge;
}
