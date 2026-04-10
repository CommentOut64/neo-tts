import { computed, ref } from "vue";
import { ElMessage } from "element-plus";

import { useEditSession } from "@/composables/useEditSession";
import { usePlayback } from "@/composables/usePlayback";
import {
  extractCommittedRenderJobPayload,
  useRuntimeState,
} from "@/composables/useRuntimeState";
import type {
  RenderJobCommittedPayload,
  RenderJobResponse,
} from "@/types/editSession";

type WorkspaceProcessingPhase =
  | "idle"
  | "submitting"
  | "processing"
  | "hydrating"
  | "failed";

type WorkspaceProcessingKind = "edge-compose" | "rerender" | null;

const AUDIO_WARM_TIMEOUT_MS = 4000;
const PROCESSING_MESSAGE_MIN_VISIBLE_MS = 2000;
const SUCCESS_MESSAGE_DURATION_MS = 2500;

interface ActiveProcessingContext {
  jobId: string | null;
  kind: WorkspaceProcessingKind;
  summary: string;
  committedSignature: string | null;
  resolve: () => void;
  reject: (error: Error) => void;
}

const phase = ref<WorkspaceProcessingPhase>("idle");
const activeJobId = ref<string | null>(null);
const activeJobKind = ref<WorkspaceProcessingKind>(null);
const pendingSummary = ref<string>("");

let activeMessage: { close: () => void } | null = null;
let activeMessageShownAt = 0;
let runtimeEventsAttached = false;
let activeContext: ActiveProcessingContext | null = null;

function resolveProcessingLabels(summary: string) {
  if (summary.includes("边界策略")) {
    return {
      submitting: `正在处理边界调整：${summary}`,
      processing: "正在处理边界调整...",
      hydrating: "正在准备新的边界试听音频...",
      completed: "边界调整已完成",
    };
  }

  return {
    submitting: `正在处理停顿调整：${summary}`,
    processing: "正在处理停顿调整...",
    hydrating: "正在准备新的试听音频...",
    completed: "停顿调整已完成",
  };
}

function closeActiveMessage() {
  activeMessage?.close();
  activeMessage = null;
  activeMessageShownAt = 0;
}

function showPersistentMessage(message: string) {
  if (activeMessage) {
    return;
  }
  closeActiveMessage();
  activeMessageShownAt = Date.now();
  activeMessage = ElMessage.info({
    message,
    duration: 0,
    showClose: false,
  });
}

function sleep(ms: number) {
  return new Promise<void>((resolve) => {
    globalThis.setTimeout(resolve, ms);
  });
}

async function ensureProcessingMessageMinimumVisible() {
  if (!activeMessage || activeMessageShownAt <= 0) {
    return;
  }

  const elapsedMs = Date.now() - activeMessageShownAt;
  const remainingMs = PROCESSING_MESSAGE_MIN_VISIBLE_MS - elapsedMs;
  if (remainingMs > 0) {
    await sleep(remainingMs);
  }
}

function resetState() {
  phase.value = "idle";
  activeJobId.value = null;
  activeJobKind.value = null;
  pendingSummary.value = "";
  activeContext = null;
}

function resolveAudioUrlsForHydration(input: {
  timelineBlockEntries:
    | Array<{ block_asset_id: string; audio_url: string }>
    | undefined;
  changedBlockAssetIds: string[];
}) {
  const blockEntries = input.timelineBlockEntries ?? [];
  if (input.changedBlockAssetIds.length === 0) {
    return blockEntries.map((entry) => entry.audio_url);
  }

  const changedBlockIdSet = new Set(input.changedBlockAssetIds);
  return blockEntries
    .filter((entry) => changedBlockIdSet.has(entry.block_asset_id))
    .map((entry) => entry.audio_url);
}

function matchesCommittedFormalState(input: {
  result: Awaited<
    ReturnType<ReturnType<typeof useEditSession>["refreshFormalSessionState"]>
  >;
  committedPayload: RenderJobCommittedPayload;
}) {
  return (
    input.result.snapshot?.document_version ===
      input.committedPayload.committed_document_version &&
    input.result.timeline?.timeline_manifest_id ===
      input.committedPayload.committed_timeline_manifest_id
  );
}

function withTimeout<T>(
  task: Promise<T>,
  timeoutMs: number,
  message: string,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = globalThis.setTimeout(() => {
      reject(new Error(message));
    }, timeoutMs);
    task.then(
      (value) => {
        globalThis.clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        globalThis.clearTimeout(timer);
        reject(error);
      },
    );
  });
}

function handleFailure(error: unknown) {
  const failure = error instanceof Error ? error : new Error("处理失败");
  phase.value = "failed";
  closeActiveMessage();
  ElMessage.error({
    message: failure.message,
    duration: 2400,
  });
  activeContext?.reject(failure);
  resetState();
}

function buildCommittedSignature(payload: RenderJobCommittedPayload) {
  return JSON.stringify(payload);
}

async function hydrateAfterCommitted(payload: RenderJobCommittedPayload) {
  if (!activeContext) {
    return;
  }

  const processingContext = activeContext;
  phase.value = "hydrating";
  showPersistentMessage(resolveProcessingLabels(processingContext.summary).hydrating);

  try {
    const editSession = useEditSession();
    const playback = usePlayback();
    const runtimeState = useRuntimeState();
    const result = await editSession.refreshFormalSessionState();
    if (!matchesCommittedFormalState({ result, committedPayload: payload })) {
      throw new Error("已拿到提交结果，但正式状态尚未切换到最新时间线，请重试");
    }

    const audioUrls = resolveAudioUrlsForHydration({
      timelineBlockEntries: result.timeline?.block_entries,
      changedBlockAssetIds: payload.changed_block_asset_ids,
    });
    await withTimeout(
      playback.warmAudioUrls(audioUrls),
      AUDIO_WARM_TIMEOUT_MS,
      "准备新音频超时，请重试",
    );

    if (processingContext.jobId) {
      await runtimeState.reconcileTrackedJobTerminal(processingContext.jobId);
    }

    await ensureProcessingMessageMinimumVisible();
    closeActiveMessage();
    ElMessage.success({
      message: resolveProcessingLabels(processingContext.summary).completed,
      duration: SUCCESS_MESSAGE_DURATION_MS,
    });
    processingContext.resolve();
    resetState();
  } catch (error) {
    handleFailure(error);
  }
}

function maybeHydrateCommittedPayload(payload: RenderJobCommittedPayload) {
  if (!activeContext) {
    return;
  }

  const signature = buildCommittedSignature(payload);
  if (activeContext.committedSignature === signature) {
    return;
  }

  activeContext.committedSignature = signature;
  void hydrateAfterCommitted(payload);
}

function ensureRuntimeBridge() {
  if (runtimeEventsAttached) {
    return;
  }
  runtimeEventsAttached = true;
  const runtimeState = useRuntimeState();

  runtimeState.onRenderJobCommitted((event) => {
    if (!activeContext || event.jobId !== activeContext.jobId) {
      return;
    }
    maybeHydrateCommittedPayload(event.payload);
  });

  runtimeState.onRenderJobEvent((event) => {
    if (
      !activeContext ||
      event.jobId !== activeContext.jobId ||
      event.type !== "job_state_changed"
    ) {
      return;
    }

    if (event.payload?.status === "failed") {
      handleFailure(new Error(event.payload?.message || "处理失败"));
      return;
    }

    if (
      ["queued", "preparing", "rendering", "composing", "committing"].includes(
        event.payload?.status,
      )
    ) {
      phase.value = "processing";
      showPersistentMessage(
        resolveProcessingLabels(activeContext.summary).processing,
      );
    }
  });
}

export function useWorkspaceProcessing() {
  ensureRuntimeBridge();
  const playback = usePlayback();
  const runtimeState = useRuntimeState();

  async function startEdgeUpdate(input: { summary: string }) {
    phase.value = "submitting";
    activeJobKind.value = "edge-compose";
    pendingSummary.value = input.summary;
    playback.pauseForProcessing();
    showPersistentMessage(resolveProcessingLabels(input.summary).submitting);

    return new Promise<void>((resolve, reject) => {
      activeContext = {
        jobId: null,
        kind: "edge-compose",
        summary: input.summary,
        committedSignature: null,
        resolve,
        reject,
      };
    });
  }

  function acceptJob(input: {
    job: RenderJobResponse;
    jobKind: Exclude<WorkspaceProcessingKind, null>;
  }) {
    if (!activeContext) {
      return;
    }

    activeContext.jobId = input.job.job_id;
    activeJobId.value = input.job.job_id;
    activeJobKind.value = input.jobKind;
    phase.value = "processing";
    showPersistentMessage(resolveProcessingLabels(activeContext.summary).processing);

    const committedPayload = extractCommittedRenderJobPayload(input.job);
    if (committedPayload) {
      maybeHydrateCommittedPayload(committedPayload);
    }
  }

  function fail(message: string) {
    handleFailure(new Error(message));
  }

  return {
    phase: computed(() => phase.value),
    activeJobId: computed(() => activeJobId.value),
    activeJobKind: computed(() => activeJobKind.value),
    pendingSummary: computed(() => pendingSummary.value),
    isInteractionLocked: computed(
      () => phase.value !== "idle" || !runtimeState.canMutate.value,
    ),
    startEdgeUpdate,
    acceptJob,
    fail,
  };
}
