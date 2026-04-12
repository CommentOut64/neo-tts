import type { ExportJobResponse, RenderJobSummary } from "@/types/editSession";
import type { InputDraftSource } from "@/composables/useInputDraft";
import { buildSegmentDisplayText } from "@/utils/segmentTextDisplay";

export type WorkspaceSessionStatus = "empty" | "initializing" | "ready" | "failed";
export type WorkspaceEntryAction = "idle" | "initialize" | "rebuild";
export type EndSessionGuard =
  | "confirm_plain"
  | "confirm_discard_only"
  | "confirm_apply_reorder"
  | "confirm_with_text_options";
export type EndSessionChoice =
  | "continue_editing"
  | "keep_working_text"
  | "apply_updates_and_end_session"
  | "discard_unapplied_changes";

interface ResolveWorkspaceEntryActionInput {
  sessionStatus: WorkspaceSessionStatus;
  hasInputText: boolean;
  inputSource: InputDraftSource;
  draftRevision: number;
  lastSentToSessionRevision: number | null;
  sourceDraftRevision: number | null;
}

interface SessionSegmentLike {
  segment_id: string;
  raw_text: string;
  order_key: number;
  terminal_raw?: string;
  terminal_closer_suffix?: string;
  terminal_source?: "original" | "synthetic";
  detected_language?: "zh" | "ja" | "en" | "unknown" | null;
}

interface ResolveNavbarRuntimeHintInput {
  currentRenderJob: RenderJobSummary | null;
  currentExportJob: ExportJobResponse | null;
}

interface ResolveEndSessionGuardInput {
  hasPendingTextChanges: boolean;
  hasPendingRerender: boolean;
  hasDirtyParameterDraft: boolean;
  hasPendingReorderDraft: boolean;
}

interface ResolveEndSessionChoiceResultInput {
  choice: EndSessionChoice;
  appliedText: string;
  workingText: string;
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

  if (input.inputSource === "input_handoff") {
    return "rebuild";
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

export function resolveEndSessionGuard(
  input: ResolveEndSessionGuardInput,
): EndSessionGuard {
  if (input.hasPendingTextChanges) {
    return "confirm_with_text_options";
  }

  if (input.hasPendingReorderDraft) {
    return "confirm_apply_reorder";
  }

  if (input.hasPendingRerender || input.hasDirtyParameterDraft) {
    return "confirm_discard_only";
  }

  return "confirm_plain";
}

export function resolveEndSessionChoiceResult(
  input: ResolveEndSessionChoiceResultInput,
): {
  shouldEndSession: boolean;
  shouldApplyUpdatesBeforeEndSession?: boolean;
  nextInputText: string | null;
  nextInputSource: InputDraftSource | null;
  nextRoute: "/workspace" | null;
} {
  if (input.choice === "continue_editing") {
    return {
      shouldEndSession: false,
      nextInputText: null,
      nextInputSource: null,
      nextRoute: null,
    };
  }

  if (input.choice === "keep_working_text") {
    return {
      shouldEndSession: true,
      nextInputText: input.workingText,
      nextInputSource: "input_handoff",
      nextRoute: "/workspace",
    };
  }

  if (input.choice === "apply_updates_and_end_session") {
    return {
      shouldEndSession: true,
      shouldApplyUpdatesBeforeEndSession: true,
      nextInputText: input.appliedText,
      nextInputSource: "applied_text",
      nextRoute: "/workspace",
    };
  }

  return {
    shouldEndSession: true,
    nextInputText: input.appliedText,
    nextInputSource: "applied_text",
    nextRoute: "/workspace",
  };
}

export function buildSessionHeadText(segments: SessionSegmentLike[]): string {
  return [...segments]
    .sort((left, right) => left.order_key - right.order_key)
    .map((segment) => buildSegmentDisplayText(segment))
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
