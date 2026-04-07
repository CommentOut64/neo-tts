import { ref, computed } from "vue";
import type {
  ExportJobResponse,
  RenderJob,
  RenderJobResponse,
  RenderJobSummary,
  RenderJobEventType,
  ProgressiveSegment,
  SegmentsInitializedPayload,
  SegmentCompletedPayload,
} from "@/types/editSession";
import {
  subscribeRenderJobEvents,
  getRenderJob,
  pauseRenderJob,
  cancelRenderJob,
  resumeRenderJob,
  subscribeExportJobEvents,
  getExportJob,
} from "@/api/editSession";

export type SseConnectionState = "connected" | "disconnected" | "polling";
export type TrackedRenderJob = RenderJob | RenderJobResponse | RenderJobSummary;
export type TrackedExportJob = ExportJobResponse;

const currentRenderJob = ref<TrackedRenderJob | null>(null);
const currentExportJob = ref<TrackedExportJob | null>(null);
const sseConnectionState = ref<SseConnectionState>("disconnected");
const progressiveSegments = ref<ProgressiveSegment[]>([]);
const isInitialRendering = ref<boolean>(false);
const lockedSegmentIds = ref<Set<string>>(new Set());

let unsubscribeSse: (() => void) | null = null;
let pollingIntervalId: ReturnType<typeof setInterval> | null = null;
let unsubscribeExportSse: (() => void) | null = null;
let exportPollingIntervalId: ReturnType<typeof setInterval> | null = null;
let finishPromise: Promise<void> | null = null;
let trackedJobId: string | null = null;
let trackedJobOptions: TrackJobOptions = {};
let trackedJobEpoch = 0;
let resolveTerminalStatus:
  | ((status: "completed" | "failed" | "paused" | "cancelled_partial") => void)
  | null = null;
let terminalStatusPromise: Promise<
  "completed" | "failed" | "paused" | "cancelled_partial"
> | null = null;

const PAUSED_HINT = "已暂停，随时可以继续";
const RESUMED_HINT = "已继续，正在接着处理剩余内容";

interface TrackJobOptions {
  initialRendering?: boolean;
  lockedSegmentIds?: string[];
  refreshSessionOnTerminal?: boolean;
  preservedProgressiveSegments?: ProgressiveSegment[];
  preservedProgress?: number;
  preservedMessage?: string;
}

interface PausedJobContext {
  jobId: string;
  options: TrackJobOptions;
  currentJob: TrackedRenderJob;
}

let pausedJobContext: PausedJobContext | null = null;

function buildTrackedJobSnapshot(
  job: TrackedRenderJob,
  options: Pick<TrackJobOptions, "preservedProgress" | "preservedMessage"> = {},
): TrackedRenderJob {
  return {
    ...job,
    progress: Math.max(job.progress ?? 0, options.preservedProgress ?? 0),
    message: job.message || options.preservedMessage || "",
  };
}

function mergeTrackedJobSnapshot(job: TrackedRenderJob): TrackedRenderJob {
  const previousJob = currentRenderJob.value;
  return {
    ...(previousJob ?? {}),
    ...job,
    progress: Math.max(previousJob?.progress ?? 0, job.progress ?? 0),
    message: job.message || previousJob?.message || "",
  };
}

function rememberPausedJob(job: TrackedRenderJob) {
  pausedJobContext = {
    jobId: job.job_id,
    options: { ...trackedJobOptions },
    currentJob: { ...job },
  };
}

function isTerminalRenderStatus(status: TrackedRenderJob["status"]) {
  return ["completed", "failed", "cancelled_partial"].includes(status);
}

function isTerminalExportStatus(status: TrackedExportJob["status"]) {
  return ["completed", "failed"].includes(status);
}

export function useRuntimeState() {
  const canMutate = computed(() => {
    return (
      currentRenderJob.value === null ||
      isTerminalRenderStatus(currentRenderJob.value.status)
    );
  });

  function trackJob(job: TrackedRenderJob, options: TrackJobOptions = {}) {
    if (!job.job_id) {
      throw new Error("Render job 缺少有效的 job_id，无法建立跟踪");
    }

    if (unsubscribeSse) unsubscribeSse();
    if (pollingIntervalId) {
      clearInterval(pollingIntervalId);
      pollingIntervalId = null;
    }

    finishPromise = null;
    trackedJobEpoch += 1;
    trackedJobId = job.job_id;
    trackedJobOptions = options;
    pausedJobContext = null;
    currentRenderJob.value = buildTrackedJobSnapshot(job, options);
    progressiveSegments.value = options.preservedProgressiveSegments
      ? [...options.preservedProgressiveSegments]
      : [];
    isInitialRendering.value = options.initialRendering ?? false;
    lockedSegmentIds.value = new Set(options.lockedSegmentIds ?? []);
    sseConnectionState.value = "connected";
    terminalStatusPromise = new Promise((resolve) => {
      resolveTerminalStatus = resolve;
    });

    unsubscribeSse = subscribeRenderJobEvents(job.job_id, {
      onEvent: (type: RenderJobEventType, payload: any) => {
        if (type === "job_state_changed") {
          currentRenderJob.value = mergeTrackedJobSnapshot(
            payload as RenderJob,
          );
          if (
            ["completed", "failed", "paused", "cancelled_partial"].includes(
              currentRenderJob.value.status,
            )
          ) {
            if (currentRenderJob.value.status === "paused") {
              rememberPausedJob(currentRenderJob.value);
            }
            resolveTerminalStatus?.(currentRenderJob.value.status);
            void finishTrackedJob(
              currentRenderJob.value.job_id,
              currentRenderJob.value.status,
            );
          }
        } else if (type === "segments_initialized") {
          const initPayload = payload as SegmentsInitializedPayload;
          progressiveSegments.value = initPayload.segments
            .map((seg: any) => ({
              segmentId: seg.segment_id,
              orderKey: seg.order_key,
              rawText: seg.raw_text,
              renderStatus: seg.render_status,
              renderAssetId: null,
            }))
            .sort((a: any, b: any) => a.orderKey - b.orderKey);
        } else if (type === "segment_completed") {
          const compPayload = payload as SegmentCompletedPayload;
          progressiveSegments.value = progressiveSegments.value.map((s) =>
            s.segmentId === compPayload.segment_id
              ? {
                  ...s,
                  renderStatus: "completed" as const,
                  renderAssetId: compPayload.render_asset_id,
                }
              : s,
          );
        } else if (type === "job_resumed") {
          if (currentRenderJob.value) {
            currentRenderJob.value = {
              ...currentRenderJob.value,
              message: RESUMED_HINT,
            };
          }
        } else if (type === "job_paused") {
          if (currentRenderJob.value) {
            currentRenderJob.value = {
              ...currentRenderJob.value,
              status: "paused",
              message: PAUSED_HINT,
            };
            rememberPausedJob(currentRenderJob.value);
          }
          resolveTerminalStatus?.("paused");
          void finishTrackedJob(
            currentRenderJob.value?.job_id ?? job.job_id,
            "paused",
          );
        } else if (type === "job_cancelled_partial") {
          resolveTerminalStatus?.("cancelled_partial");
          void finishTrackedJob(
            currentRenderJob.value?.job_id ?? job.job_id,
            "cancelled_partial",
          );
        }
      },
      onError: (err: any) => {
        console.warn("SSE disconnected, falling back to polling", err);
        sseConnectionState.value = "polling";
        if (unsubscribeSse) unsubscribeSse();
        unsubscribeSse = null;
        startPolling(job.job_id);
      },
    });
  }

  function startPolling(jobId: string) {
    if (pollingIntervalId) {
      clearInterval(pollingIntervalId);
    }

    pollingIntervalId = setInterval(async () => {
      try {
        const job = await getRenderJob(jobId);
        currentRenderJob.value = mergeTrackedJobSnapshot(job);
        if (
          ["completed", "failed", "paused", "cancelled_partial"].includes(
            job.status,
          )
        ) {
          if (pollingIntervalId) {
            clearInterval(pollingIntervalId);
            pollingIntervalId = null;
          }
          if (job.status === "paused") {
            rememberPausedJob(currentRenderJob.value);
          }
          resolveTerminalStatus?.(job.status);
          void finishTrackedJob(job.job_id, job.status);
        }
      } catch (err) {
        console.error("Polling error", err);
      }
    }, 2000);
  }

  async function finishTrackedJob(
    settledJobId: string | null,
    settledStatus: "completed" | "failed" | "paused" | "cancelled_partial",
  ) {
    if (finishPromise) {
      await finishPromise;
      return;
    }

    const settleEpoch = trackedJobEpoch;
    const pendingFinish = (async () => {
      if (unsubscribeSse) {
        unsubscribeSse();
        unsubscribeSse = null;
      }
      if (pollingIntervalId) {
        clearInterval(pollingIntervalId);
        pollingIntervalId = null;
      }

      try {
        const stillSameJob =
          trackedJobId === settledJobId && trackedJobEpoch === settleEpoch;
        if (
          stillSameJob &&
          trackedJobOptions.refreshSessionOnTerminal !== false
        ) {
          const module = await import("./useEditSession");
          const editSession = module.useEditSession();
          await editSession.refreshSnapshot();
          if (editSession.sessionStatus.value === "ready") {
            await editSession.refreshTimeline();
          }
        }
      } catch (err) {
        console.error(
          "Failed to refresh edit session after render job settled",
          err,
        );
      } finally {
        const stillSameJob =
          trackedJobId === settledJobId && trackedJobEpoch === settleEpoch;
        if (!stillSameJob) {
          return;
        }

        const keepPausedContext = settledStatus === "paused";
        if (isTerminalRenderStatus(settledStatus)) {
          currentRenderJob.value = null;
        }
        if (!keepPausedContext) {
          progressiveSegments.value = [];
          isInitialRendering.value = false;
          lockedSegmentIds.value = new Set();
        }
        sseConnectionState.value = "disconnected";
        trackedJobId = null;
        trackedJobOptions = {};
        if (!keepPausedContext) {
          pausedJobContext = null;
        }
      }
    })();
    finishPromise = pendingFinish;

    try {
      await pendingFinish;
    } finally {
      if (finishPromise === pendingFinish) {
        finishPromise = null;
      }
      if (trackedJobId === settledJobId && trackedJobEpoch === settleEpoch) {
        resolveTerminalStatus = null;
        terminalStatusPromise = null;
      }
    }
  }

  async function pauseJob() {
    if (currentRenderJob.value) {
      await pauseRenderJob(currentRenderJob.value.job_id);
    }
  }

  async function cancelJob() {
    if (currentRenderJob.value) {
      await cancelRenderJob(currentRenderJob.value.job_id);
    }
  }

  async function resumeJob() {
    const pausedContext = pausedJobContext;
    const pausedJobId = pausedContext?.jobId ?? currentRenderJob.value?.job_id;
    if (!pausedJobId) {
      throw new Error("当前没有可恢复的推理任务");
    }

    const nextJob = await resumeRenderJob(pausedJobId);
    trackJob(nextJob, {
      ...(pausedContext?.options ?? {}),
      preservedProgressiveSegments: pausedContext
        ? [...progressiveSegments.value]
        : undefined,
      preservedProgress: pausedContext?.currentJob.progress,
      preservedMessage: pausedContext?.currentJob.message,
    });
  }

  function clearExportTracking() {
    if (unsubscribeExportSse) {
      unsubscribeExportSse();
      unsubscribeExportSse = null;
    }
    if (exportPollingIntervalId) {
      clearInterval(exportPollingIntervalId);
      exportPollingIntervalId = null;
    }
    currentExportJob.value = null;
  }

  function trackExportJob(job: TrackedExportJob) {
    clearExportTracking();
    currentExportJob.value = { ...job };

    unsubscribeExportSse = subscribeExportJobEvents(job.export_job_id, {
      onStateChanged(nextJob) {
        currentExportJob.value = { ...(currentExportJob.value ?? {}), ...nextJob };
        if (isTerminalExportStatus(nextJob.status)) {
          clearExportTracking();
        }
      },
      onProgress(progress, message) {
        if (!currentExportJob.value) {
          return;
        }
        currentExportJob.value = {
          ...currentExportJob.value,
          progress,
          message,
          status: "exporting",
        };
      },
      onCompleted(nextJob) {
        currentExportJob.value = { ...nextJob };
        clearExportTracking();
      },
      onError() {
        if (unsubscribeExportSse) {
          unsubscribeExportSse();
          unsubscribeExportSse = null;
        }
        exportPollingIntervalId = setInterval(async () => {
          try {
            const nextJob = await getExportJob(job.export_job_id);
            currentExportJob.value = nextJob;
            if (isTerminalExportStatus(nextJob.status)) {
              clearExportTracking();
            }
          } catch (err) {
            console.error("Export polling error", err);
          }
        }, 2000);
      },
    });
  }

  async function waitForJobTerminal(jobId: string) {
    if (trackedJobId !== jobId || terminalStatusPromise === null) {
      throw new Error(`未找到正在跟踪的 job: ${jobId}`);
    }

    return terminalStatusPromise;
  }

  return {
    currentRenderJob,
    currentExportJob,
    sseConnectionState,
    progressiveSegments,
    isInitialRendering,
    lockedSegmentIds,
    canMutate,
    trackJob,
    trackExportJob,
    clearExportTracking,
    pauseJob,
    cancelJob,
    resumeJob,
    waitForJobTerminal,
  };
}
