import type { RenderJobStatus } from "@/types/editSession";
import type { InferenceProgressState } from "@/types/tts";

export type PrimaryRenderActionKind = "pause" | "resume";
export type WorkspaceProgressSource = "tts" | "idle";

export interface WorkspaceProgressState {
  percent: number;
  message: string;
  source: WorkspaceProgressSource;
}

export function getPrimaryRenderActionKind(
  status: RenderJobStatus | undefined,
): PrimaryRenderActionKind {
  return status === "paused" ? "resume" : "pause";
}

export function getPrimaryRenderActionLabel(
  status: RenderJobStatus | undefined,
): string {
  return getPrimaryRenderActionKind(status) === "resume" ? "恢复" : "暂停";
}

function isActiveInferenceStatus(status: InferenceProgressState["status"] | undefined): boolean {
  return status === "preparing" || status === "inferencing" || status === "cancelling";
}

function formatInferenceMessage(progress: InferenceProgressState): string {
  if (progress.current_segment != null && progress.total_segments != null) {
    return `${progress.message} (${progress.current_segment}/${progress.total_segments} 段)`;
  }

  return progress.message || progress.status;
}

export function resolveWorkspaceProgressState({
  inferenceProgress,
}: {
  inferenceProgress?: InferenceProgressState | null;
  renderJob?: RenderJob | null;
}): WorkspaceProgressState {
  if (inferenceProgress && isActiveInferenceStatus(inferenceProgress.status)) {
    return {
      percent: Math.round(inferenceProgress.progress * 100),
      message: formatInferenceMessage(inferenceProgress),
      source: "tts",
    };
  }

  return {
    percent: 0,
    message: "等待中...",
    source: "idle",
  };
}
