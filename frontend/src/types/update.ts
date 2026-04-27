export type AppUpdateStatus =
  | "idle"
  | "checking"
  | "up-to-date"
  | "update-available"
  | "bootstrap-upgrade-required"
  | "downloading"
  | "ready-to-restart"
  | "switching"
  | "error";

export interface AppUpdateProgress {
  totalPackages: number;
  completedPackages: number;
  currentPackageId?: string;
  currentPackageVersion?: string;
  currentPackageBytes?: number;
  currentPackageTotal?: number;
}

export interface AppUpdateState {
  status: AppUpdateStatus;
  releaseId?: string;
  notesUrl?: string;
  changedPackages?: string[];
  estimatedDownloadBytes?: number;
  minBootstrapVersion?: string;
  progress?: AppUpdateProgress;
  errorCode?: string;
  errorMessage?: string;
}

export interface AppUpdateCheckRequest {
  channel: string;
  automatic: boolean;
}

export interface AppUpdateCheckResponse {
  status: Exclude<AppUpdateStatus, "idle" | "checking" | "switching">;
  releaseId?: string;
  notesUrl?: string;
  changedPackages?: string[];
  estimatedDownloadBytes?: number;
  minBootstrapVersion?: string;
  progress?: AppUpdateProgress;
  errorCode?: string;
  errorMessage?: string;
}

export interface AppUpdateDownloadRequest {
  releaseId?: string;
}

export interface AppUpdateDownloadResponse {
  status: "downloading" | "ready-to-restart" | "accepted";
  releaseId?: string;
  progress?: AppUpdateProgress;
  errorCode?: string;
  message?: string;
}

export interface AppUpdateRestartRequest {
  releaseId?: string;
}

export interface AppUpdateRestartResponse {
  status: "switching" | "accepted";
  releaseId?: string;
}
