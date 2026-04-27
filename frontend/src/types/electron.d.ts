import type {
  AppUpdateCheckRequest,
  AppUpdateCheckResponse,
  AppUpdateDownloadRequest,
  AppUpdateDownloadResponse,
  AppUpdateRestartRequest,
  AppUpdateRestartResponse,
} from "@/types/update";

export {};

declare global {
  interface Window {
    neoTTS?: {
      runtime: "electron";
      distributionKind: "installed" | "portable";
      backendOrigin: string;
      requestAppExit(): Promise<void>;
      checkForAppUpdate(request: AppUpdateCheckRequest): Promise<AppUpdateCheckResponse>;
      startAppUpdateDownload(
        request: AppUpdateDownloadRequest,
      ): Promise<AppUpdateDownloadResponse>;
      restartAndApplyAppUpdate(
        request: AppUpdateRestartRequest,
      ): Promise<AppUpdateRestartResponse>;
      openExternalUrl(url: string): Promise<void>;
      getPathForFile(file: File): string | null;
    };
  }
}
