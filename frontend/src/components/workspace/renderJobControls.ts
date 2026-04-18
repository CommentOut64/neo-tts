import type { RenderJobStatus, RenderJobResponse } from "@/types/editSession";
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

function isActiveInferenceStatus(
  status: InferenceProgressState["status"] | undefined,
): boolean {
  return (
    status === "preparing" ||
    status === "inferencing" ||
    status === "cancelling"
  );
}

function formatInferenceMessage(progress: InferenceProgressState): string {
  if (progress.status === "cancelling") {
    return "正在取消...";
  }
  if (progress.current_segment != null && progress.total_segments != null) {
    return `正在生成语音 (${progress.current_segment}/${progress.total_segments} 段)`;
  }
  return "正在生成语音...";
}

export function resolveWorkspaceProgressState({
  inferenceProgress,
  renderJob,
}: {
  inferenceProgress?: InferenceProgressState | null;
  renderJob?: RenderJobResponse | null;
}): WorkspaceProgressState {
  const inferenceActive = Boolean(
    inferenceProgress && isActiveInferenceStatus(inferenceProgress.status),
  );
  const inferencePercent = Math.round((inferenceProgress?.progress ?? 0) * 100);
  const renderJobPercent = Math.round((renderJob?.progress ?? 0) * 100);
  const renderJobPreparing = Boolean(
    renderJob && ["queued", "preparing"].includes(renderJob.status),
  );

  if (renderJobPreparing && (!inferenceActive || renderJobPercent > inferencePercent)) {
    return {
      percent: Math.max(renderJobPercent, inferencePercent),
      message: "加载中...",
      source: "idle",
    };
  }

  if (inferenceProgress && isActiveInferenceStatus(inferenceProgress.status)) {
    return {
      percent: inferencePercent,
      message: formatInferenceMessage(inferenceProgress),
      source: "tts",
    };
  }

  const inferenceActuallyFinished =
    inferenceProgress?.status === "completed" &&
    (!renderJob || !["queued", "preparing"].includes(renderJob.status));

  if (
    inferenceActuallyFinished ||
    (renderJob &&
      ["composing", "committing", "completed"].includes(renderJob.status))
  ) {
    return {
      percent: 100,
      message: "生成完成，正在同步...",
      source: "tts",
    };
  }

  return {
    percent: 0,
    message: "加载中...",
    source: "idle",
  };
}
