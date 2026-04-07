import type { ExportJobResponse, RenderJobSummary } from "@/types/editSession";

export type WorkspaceSessionStatus = "empty" | "initializing" | "ready" | "failed";
export type WorkspaceEntryAction = "idle" | "initialize" | "rebuild";

interface ResolveWorkspaceEntryActionInput {
  sessionStatus: WorkspaceSessionStatus;
  hasInputText: boolean;
  draftRevision: number;
  lastSentToSessionRevision: number | null;
  sourceDraftRevision: number | null;
}

interface SessionSegmentLike {
  segment_id: string;
  raw_text: string;
  order_key: number;
}

interface ResolveNavbarRuntimeHintInput {
  currentRenderJob: RenderJobSummary | null;
  currentExportJob: ExportJobResponse | null;
}

function isTerminalExportStatus(status: ExportJobResponse["status"]) {
  return ["completed", "failed"].includes(status);
}

function isTerminalRenderStatus(status: RenderJobSummary["status"]) {
  return ["completed", "failed", "cancelled_partial"].includes(status);
}

export function isExportBlockedByRenderJob(job: RenderJobSummary | null): boolean {
  if (!job) {
    return false;
  }

  return [
    "queued",
    "preparing",
    "rendering",
    "composing",
    "committing",
    "pause_requested",
    "cancel_requested",
  ].includes(job.status);
}

export function resolveWorkspaceEntryAction(
  input: ResolveWorkspaceEntryActionInput,
): WorkspaceEntryAction {
  if (!input.hasInputText) {
    return "idle";
  }

  if (input.sessionStatus === "empty" || input.sessionStatus === "failed") {
    return "initialize";
  }

  if (input.sessionStatus !== "ready") {
    return "idle";
  }

  if (input.sourceDraftRevision === null) {
    return "rebuild";
  }

  if (input.draftRevision !== input.sourceDraftRevision) {
    return "rebuild";
  }

  if (
    input.lastSentToSessionRevision !== null &&
    input.lastSentToSessionRevision !== input.draftRevision
  ) {
    return "rebuild";
  }

  return "idle";
}

export function buildSessionHeadText(segments: SessionSegmentLike[]): string {
  return [...segments]
    .sort((left, right) => left.order_key - right.order_key)
    .map((segment) => segment.raw_text)
    .join("");
}

export function isRelativeTargetDir(targetDir: string): boolean {
  const normalized = targetDir.trim();
  if (!normalized) {
    return false;
  }

  if (/^[a-zA-Z]:[\\/]/.test(normalized)) {
    return false;
  }

  if (normalized.startsWith("/") || normalized.startsWith("\\") || normalized.startsWith("..")) {
    return false;
  }

  return !normalized.split(/[\\/]+/).some((part) => part === "..");
}

export function resolveNavbarRuntimeHint(
  input: ResolveNavbarRuntimeHintInput,
): "已暂停" | "推理中" | "导出中" | null {
  if (input.currentRenderJob && !isTerminalRenderStatus(input.currentRenderJob.status)) {
    return input.currentRenderJob.status === "paused" ? "已暂停" : "推理中";
  }

  if (input.currentExportJob && !isTerminalExportStatus(input.currentExportJob.status)) {
    return "导出中";
  }

  return null;
}
