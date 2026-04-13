import { ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";

import { pauseRenderJob, waitForRenderJobTerminal } from "@/api/editSession";
import { useInferenceRuntime } from "@/composables/useInferenceRuntime";
import { useParameterPanel } from "@/composables/useParameterPanel";
import { useRuntimeState } from "@/composables/useRuntimeState";
import { useWorkspaceExitBridge } from "@/composables/useWorkspaceExitBridge";
import { getRuntimeHost } from "@/platform/runtimeHost";
import type { ExitChoice } from "@/types/system";
import type { RenderJobStatus } from "@/types/editSession";
import type { InferenceProgressStatus } from "@/types/tts";

const isExiting = ref(false);

const ACTIVE_RENDER_JOB_STATUSES = new Set<RenderJobStatus>([
  "queued",
  "preparing",
  "rendering",
  "composing",
  "committing",
  "pause_requested",
  "cancel_requested",
]);

const TERMINAL_RENDER_JOB_STATUSES = new Set<RenderJobStatus>([
  "paused",
  "completed",
  "failed",
  "cancelled_partial",
]);

const ACTIVE_INFERENCE_STATUSES = new Set<InferenceProgressStatus>([
  "preparing",
  "inferencing",
  "cancelling",
]);

const TERMINAL_INFERENCE_STATUSES = new Set<InferenceProgressStatus>([
  "idle",
  "completed",
  "cancelled",
  "error",
]);

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    globalThis.setTimeout(resolve, ms);
  });
}

async function resolveExitChoice(hasPendingChanges: boolean): Promise<ExitChoice> {
  if (!hasPendingChanges) {
    try {
      await ElMessageBox.confirm("确定要退出应用吗？", "退出应用", {
        confirmButtonText: "确认退出",
        cancelButtonText: "取消",
        type: "warning",
        lockScroll: false,
      });
      return "save_and_exit";
    } catch {
      return "continue_editing";
    }
  }

  try {
    await ElMessageBox.confirm(
      "检测到当前仍有未决修改，是否保存后退出？",
      "退出应用",
      {
        confirmButtonText: "保存修改并退出",
        cancelButtonText: "放弃修改并退出",
        distinguishCancelAndClose: true,
        closeOnClickModal: false,
        closeOnPressEscape: false,
        type: "warning",
        lockScroll: false,
      },
    );
    return "save_and_exit";
  } catch (action) {
    if (action === "cancel") {
      return "discard_and_exit";
    }
    if (action === "close") {
      return "continue_editing";
    }
    throw action;
  }
}

async function stopActiveRenderJob(): Promise<RenderJobStatus | null> {
  const { currentRenderJob } = useRuntimeState();
  const job = currentRenderJob.value;
  if (!job) {
    return null;
  }

  if (TERMINAL_RENDER_JOB_STATUSES.has(job.status)) {
    return job.status;
  }

  if (!ACTIVE_RENDER_JOB_STATUSES.has(job.status)) {
    return job.status;
  }

  if (job.status !== "pause_requested" && job.status !== "cancel_requested") {
    await pauseRenderJob(job.job_id);
  }

  return waitForRenderJobTerminal(job.job_id);
}

async function stopActiveInferenceTask(): Promise<InferenceProgressStatus> {
  const { progress, requestForcePause, refreshProgress } =
    useInferenceRuntime("app-exit");
  if (!ACTIVE_INFERENCE_STATUSES.has(progress.value.status)) {
    return progress.value.status;
  }

  let nextState = (await requestForcePause()).state;
  let attempts = 0;
  while (!TERMINAL_INFERENCE_STATUSES.has(nextState.status)) {
    attempts += 1;
    if (attempts > 20) {
      throw new Error("等待旧版推理任务停止超时");
    }
    await delay(200);
    nextState = await refreshProgress("app-exit:wait-terminal");
  }

  return nextState.status;
}

async function stopActiveTasks(): Promise<void> {
  await stopActiveRenderJob();
  await stopActiveInferenceTask();
}

export function useAppExit() {
  const parameterPanel = useParameterPanel();
  const runtimeHost = getRuntimeHost();

  async function requestExit(): Promise<void> {
    if (isExiting.value) {
      return;
    }

    const workspaceExitBridge = useWorkspaceExitBridge();
    const hasPendingTextChanges = workspaceExitBridge.hasPendingTextChanges();
    const hasDirtyParameterDraft = parameterPanel.hasDirty.value;
    const hasPendingChanges = hasPendingTextChanges || hasDirtyParameterDraft;
    const choice = await resolveExitChoice(hasPendingChanges);
    if (choice === "continue_editing") {
      return;
    }

    isExiting.value = true;
    try {
      await stopActiveTasks();

      if (choice === "save_and_exit") {
        if (hasPendingTextChanges) {
          workspaceExitBridge.flushDraft();
        }
        if (hasDirtyParameterDraft) {
          await parameterPanel.submitDraft();
        }
      }

      const result = await runtimeHost.requestExit();

      if (choice === "discard_and_exit") {
        if (hasPendingTextChanges) {
          workspaceExitBridge.clearDraft();
        }
        if (hasDirtyParameterDraft) {
          parameterPanel.discardDraft();
        }
      }

      if (result.launcherExitRequested) {
        ElMessage.success("退出请求已提交，应用即将关闭");
      } else {
        ElMessage.info("退出准备已完成，请手动关闭页面或进程");
      }
    } catch (error) {
      ElMessage.error(
        error instanceof Error ? error.message : "退出准备失败，请稍后重试",
      );
      throw error;
    } finally {
      isExiting.value = false;
    }
  }

  return {
    isExiting,
    requestExit,
  };
}
