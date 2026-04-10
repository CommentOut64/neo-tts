import { ref, computed } from "vue";
import type {
  ExportJobResponse,
  RenderJob,
  RenderJobCommittedPayload,
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

interface RenderJobCommitMetadataShape {
  committed_document_version?: number | null;
  committed_timeline_manifest_id?: string | null;
  committed_playable_sample_span?: [number, number] | null;
  changed_block_asset_ids?: string[];
  document_version?: number | null;
  timeline_manifest_id?: string | null;
  playable_sample_span?: [number, number] | null;
}

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
const renderJobEventListeners = new Set<
  (event: { type: RenderJobEventType; payload: any; jobId: string | null }) => void
>();
const renderJobCommittedListeners = new Set<
  (event: { payload: RenderJobCommittedPayload; jobId: string | null }) => void
>();
let emittedCommittedSignature: string | null = null;

function emitRenderJobEvent(
  type: RenderJobEventType,
  payload: any,
  fallbackJobId: string | null,
) {
  for (const listener of renderJobEventListeners) {
    listener({
      type,
      payload,
      jobId: currentRenderJob.value?.job_id ?? fallbackJobId,
    });
  }
}

function normalizePlayableSampleSpan(input: unknown): [number, number] | null {
  if (!Array.isArray(input) || input.length !== 2) {
    return null;
  }
  const [start, end] = input;
  if (typeof start !== "number" || typeof end !== "number") {
    return null;
  }
  return [start, end];
}

export function extractCommittedRenderJobPayload(
  payload: Partial<RenderJobCommitMetadataShape> | null | undefined,
): RenderJobCommittedPayload | null {
  if (!payload) {
    return null;
  }

  const committedDocumentVersion =
    typeof payload.committed_document_version === "number"
      ? payload.committed_document_version
      : typeof payload.document_version === "number"
        ? payload.document_version
        : null;
  const committedTimelineManifestId =
    typeof payload.committed_timeline_manifest_id === "string"
      ? payload.committed_timeline_manifest_id
      : typeof payload.timeline_manifest_id === "string"
        ? payload.timeline_manifest_id
        : null;

  if (committedDocumentVersion === null || committedTimelineManifestId === null) {
    return null;
  }

  return {
    committed_document_version: committedDocumentVersion,
    committed_timeline_manifest_id: committedTimelineManifestId,
    committed_playable_sample_span: normalizePlayableSampleSpan(
      payload.committed_playable_sample_span ?? payload.playable_sample_span,
    ),
    changed_block_asset_ids: Array.isArray(payload.changed_block_asset_ids)
      ? payload.changed_block_asset_ids.filter(
          (blockAssetId): blockAssetId is string => typeof blockAssetId === "string",
        )
      : [],
  };
}

function buildCommittedSignature(payload: RenderJobCommittedPayload) {
  return JSON.stringify(payload);
}

function applyCommittedPayload(
  payload: RenderJobCommittedPayload,
  fallbackJobId: string | null,
) {
  if (currentRenderJob.value?.job_id) {
    currentRenderJob.value = {
      ...currentRenderJob.value,
      ...payload,
    };
  }

  const signature = buildCommittedSignature(payload);
  if (signature === emittedCommittedSignature) {
    return;
  }
  emittedCommittedSignature = signature;

  for (const listener of renderJobCommittedListeners) {
    listener({
      payload,
      jobId: currentRenderJob.value?.job_id ?? fallbackJobId,
    });
  }
}

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

function isSettledRenderStatus(
  status: TrackedRenderJob["status"],
): status is "completed" | "failed" | "paused" | "cancelled_partial" {
  return ["completed", "failed", "paused", "cancelled_partial"].includes(status);
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
    emittedCommittedSignature = null;
    currentRenderJob.value = buildTrackedJobSnapshot(job, options);
    const initialCommittedPayload = extractCommittedRenderJobPayload(
      currentRenderJob.value as Partial<RenderJobCommitMetadataShape>,
    );
    if (initialCommittedPayload) {
      applyCommittedPayload(initialCommittedPayload, job.job_id);
    }
    progressiveSegments.value = options.preservedProgressiveSegments
      ? [...options.preservedProgressiveSegments]
      : [];
    isInitialRendering.value = options.initialRendering ?? false;
    lockedSegmentIds.value = new Set(options.lockedSegmentIds ?? []);
    sseConnectionState.value = "connected";
    console.warn("[useRuntimeState] tracking render job", {
      jobId: job.job_id,
      initialRendering: isInitialRendering.value,
      lockedSegmentCount: lockedSegmentIds.value.size,
      preservedProgressiveSegmentCount: progressiveSegments.value.length,
      refreshSessionOnTerminal: options.refreshSessionOnTerminal ?? true,
    });
    terminalStatusPromise = new Promise((resolve) => {
      resolveTerminalStatus = resolve;
    });

    unsubscribeSse = subscribeRenderJobEvents(job.job_id, {
      onEvent: (type: RenderJobEventType, payload: any) => {
        emitRenderJobEvent(type, payload, job.job_id);
        if (type === "job_state_changed") {
          currentRenderJob.value = mergeTrackedJobSnapshot(
            payload as RenderJob,
          );
          const committedPayload = extractCommittedRenderJobPayload(
            payload as Partial<RenderJobCommitMetadataShape>,
          );
          if (committedPayload) {
            applyCommittedPayload(committedPayload, job.job_id);
          }
          if (isSettledRenderStatus(currentRenderJob.value.status)) {
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
          console.warn("[useRuntimeState] received segments_initialized", {
            jobId: job.job_id,
            segmentCount: progressiveSegments.value.length,
            sseConnectionState: sseConnectionState.value,
          });
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
        } else if (type === "timeline_committed") {
          const committedPayload = extractCommittedRenderJobPayload(
            payload as Partial<RenderJobCommitMetadataShape>,
          );
          if (committedPayload) {
            applyCommittedPayload(committedPayload, job.job_id);
          }
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
        console.warn("[useRuntimeState] render job SSE disconnected, falling back to polling", {
          jobId: job.job_id,
          error: err,
          progressiveSegmentCount: progressiveSegments.value.length,
          isInitialRendering: isInitialRendering.value,
        });
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
        emitRenderJobEvent("job_state_changed", job, jobId);
        const committedPayload = extractCommittedRenderJobPayload(
          job as Partial<RenderJobCommitMetadataShape>,
        );
        if (committedPayload) {
          applyCommittedPayload(committedPayload, jobId);
        }
        if (isSettledRenderStatus(job.status)) {
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

  async function reconcileTrackedJobTerminal(jobId: string) {
    if (trackedJobId !== jobId) {
      return null;
    }

    const job = await getRenderJob(jobId);
    currentRenderJob.value = mergeTrackedJobSnapshot(job);
    emitRenderJobEvent("job_state_changed", job, jobId);

    const committedPayload = extractCommittedRenderJobPayload(
      job as Partial<RenderJobCommitMetadataShape>,
    );
    if (committedPayload) {
      applyCommittedPayload(committedPayload, jobId);
    }

    if (!isSettledRenderStatus(job.status)) {
      return null;
    }

    if (job.status === "paused") {
      rememberPausedJob(currentRenderJob.value);
    }
    resolveTerminalStatus?.(job.status);
    await finishTrackedJob(job.job_id, job.status);
    return job.status;
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

  function onRenderJobEvent(
    listener: (event: {
      type: RenderJobEventType;
      payload: any;
      jobId: string | null;
    }) => void,
  ) {
    renderJobEventListeners.add(listener);
    return () => {
      renderJobEventListeners.delete(listener);
    };
  }

  function onRenderJobCommitted(
    listener: (event: {
      payload: RenderJobCommittedPayload;
      jobId: string | null;
    }) => void,
  ) {
    renderJobCommittedListeners.add(listener);
    return () => {
      renderJobCommittedListeners.delete(listener);
    };
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
    reconcileTrackedJobTerminal,
    waitForJobTerminal,
    onRenderJobEvent,
    onRenderJobCommitted,
  };
}
