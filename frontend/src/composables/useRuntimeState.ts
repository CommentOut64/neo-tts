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
import { buildSegmentDisplayText } from "@/utils/segmentTextDisplay";

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
let renderJobReconnectTimerId: ReturnType<typeof setTimeout> | null = null;
let renderJobReconnectAttempt = 0;
let renderJobHealthCheckIntervalId: ReturnType<typeof setInterval> | null = null;
let runtimeLifecycleDiagnosticsRegistered = false;
let scheduleRenderJobReconnectFromLifecycle: ((reason: string) => void) | null = null;
let lastRenderJobSseActivityAt = 0;
let resolveTerminalStatus:
  | ((status: "completed" | "failed" | "paused" | "cancelled_partial") => void)
  | null = null;
let terminalStatusPromise: Promise<
  "completed" | "failed" | "paused" | "cancelled_partial"
> | null = null;

const PAUSED_HINT = "已暂停，随时可以继续";
const RESUMED_HINT = "已继续，正在接着处理剩余内容";
const RENDER_JOB_RECONNECT_DELAYS_MS = [500, 1000, 2000] as const;
const RENDER_JOB_HEALTH_CHECK_INTERVAL_MS = 5000;
const RENDER_JOB_STREAM_STALE_MS = 30000;

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

function isPageVisible() {
  return typeof document === "undefined" || document.visibilityState === "visible";
}

function markRenderJobSseActivity() {
  lastRenderJobSseActivityAt = Date.now();
}

function clearRenderJobHealthCheckInterval() {
  if (renderJobHealthCheckIntervalId === null) {
    return;
  }
  clearInterval(renderJobHealthCheckIntervalId);
  renderJobHealthCheckIntervalId = null;
}

function ensureRenderJobHealthCheckLoop() {
  if (!shouldTrackJobLifecycle()) {
    clearRenderJobHealthCheckInterval();
    return;
  }
  if (renderJobHealthCheckIntervalId !== null) {
    return;
  }

  renderJobHealthCheckIntervalId = setInterval(() => {
    if (!shouldTrackJobLifecycle() || !isPageVisible()) {
      return;
    }
    if (sseConnectionState.value === "polling") {
      return;
    }
    if (unsubscribeSse === null || sseConnectionState.value !== "connected") {
      console.warn("[useRuntimeState] health check detected missing render job SSE", {
        jobId: trackedJobId,
        sseConnectionState: sseConnectionState.value,
        hasSubscription: unsubscribeSse !== null,
      });
      scheduleRenderJobReconnectFromLifecycle?.("health-check:disconnected");
      return;
    }

    const streamInactiveForMs =
      lastRenderJobSseActivityAt > 0 ? Date.now() - lastRenderJobSseActivityAt : null;
    if (
      streamInactiveForMs !== null &&
      streamInactiveForMs >= RENDER_JOB_STREAM_STALE_MS
    ) {
      console.warn("[useRuntimeState] health check detected stale render job SSE", {
        jobId: trackedJobId,
        streamInactiveForMs,
      });
      unsubscribeSse();
      unsubscribeSse = null;
      sseConnectionState.value = "disconnected";
      scheduleRenderJobReconnectFromLifecycle?.("health-check:stale");
    }
  }, RENDER_JOB_HEALTH_CHECK_INTERVAL_MS);
}

export function useRuntimeState() {
  registerRuntimeLifecycleDiagnostics();

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
    clearRenderJobReconnectTimer();

    finishPromise = null;
    renderJobReconnectAttempt = 0;
    trackedJobEpoch += 1;
    trackedJobId = job.job_id;
    trackedJobOptions = options;
    pausedJobContext = null;
    emittedCommittedSignature = null;
    currentRenderJob.value = buildTrackedJobSnapshot(job, options);
    lastRenderJobSseActivityAt = 0;
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
    sseConnectionState.value = "disconnected";
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

    ensureRenderJobHealthCheckLoop();
    connectRenderJobSse(job.job_id, trackedJobEpoch, "trackJob");
  }

  function connectRenderJobSse(
    jobId: string,
    jobEpoch: number,
    source: string,
  ) {
    if (trackedJobId !== jobId || trackedJobEpoch !== jobEpoch) {
      return;
    }

    if (unsubscribeSse) {
      unsubscribeSse();
      unsubscribeSse = null;
    }

    sseConnectionState.value = "disconnected";
    unsubscribeSse = subscribeRenderJobEvents(jobId, {
      onOpen: () => {
        clearRenderJobReconnectTimer();
        renderJobReconnectAttempt = 0;
        sseConnectionState.value = "connected";
        markRenderJobSseActivity();
        console.warn("[useRuntimeState] render job SSE opened", {
          jobId,
          source,
        });
      },
      onEvent: (type: RenderJobEventType, payload: any) => {
        markRenderJobSseActivity();
        emitRenderJobEvent(type, payload, jobId);
        if (type === "job_state_changed") {
          currentRenderJob.value = mergeTrackedJobSnapshot(
            payload as RenderJob,
          );
          const committedPayload = extractCommittedRenderJobPayload(
            payload as Partial<RenderJobCommitMetadataShape>,
          );
          if (committedPayload) {
            applyCommittedPayload(committedPayload, jobId);
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
              displayText: buildSegmentDisplayText({
                raw_text: seg.raw_text,
                terminal_raw: seg.terminal_raw,
                terminal_closer_suffix: seg.terminal_closer_suffix,
                terminal_source: seg.terminal_source,
                detected_language: seg.detected_language,
              }),
              renderStatus: seg.render_status,
              renderAssetId: null,
            }))
            .sort((a: any, b: any) => a.orderKey - b.orderKey);
          console.warn("[useRuntimeState] received segments_initialized", {
            jobId,
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
            applyCommittedPayload(committedPayload, jobId);
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
            currentRenderJob.value?.job_id ?? jobId,
            "paused",
          );
        } else if (type === "job_cancelled_partial") {
          resolveTerminalStatus?.("cancelled_partial");
          void finishTrackedJob(
            currentRenderJob.value?.job_id ?? jobId,
            "cancelled_partial",
          );
        }
      },
      onError: (err: any) => {
        console.warn("[useRuntimeState] render job SSE disconnected, scheduling reconnect", {
          jobId,
          error: err,
          progressiveSegmentCount: progressiveSegments.value.length,
          isInitialRendering: isInitialRendering.value,
          source,
          reconnectAttempt: renderJobReconnectAttempt,
        });
        if (unsubscribeSse) unsubscribeSse();
        unsubscribeSse = null;
        sseConnectionState.value = "disconnected";
        scheduleRenderJobReconnect(`error:${source}`);
      },
    });
    ensureRenderJobHealthCheckLoop();
  }

  function scheduleRenderJobReconnect(reason: string) {
    if (!shouldTrackJobLifecycle() || trackedJobId === null) {
      return;
    }
    if (renderJobReconnectTimerId !== null) {
      return;
    }

    const nextAttempt = renderJobReconnectAttempt + 1;
    if (nextAttempt > 3) {
      console.warn("[useRuntimeState] render job SSE reconnect exhausted, switching to polling", {
        jobId: trackedJobId,
        reason,
      });
      sseConnectionState.value = "polling";
      startPolling(trackedJobId);
      return;
    }

    renderJobReconnectAttempt = nextAttempt;
    const delayMs =
      RENDER_JOB_RECONNECT_DELAYS_MS[nextAttempt - 1] ??
      RENDER_JOB_RECONNECT_DELAYS_MS[RENDER_JOB_RECONNECT_DELAYS_MS.length - 1];
    console.warn("[useRuntimeState] scheduling render job SSE reconnect", {
      jobId: trackedJobId,
      reason,
      attempt: nextAttempt,
      delayMs,
    });

    const reconnectJobId = trackedJobId;
    const reconnectEpoch = trackedJobEpoch;
    renderJobReconnectTimerId = setTimeout(() => {
      renderJobReconnectTimerId = null;
      if (trackedJobId !== reconnectJobId || trackedJobEpoch !== reconnectEpoch) {
        return;
      }
      connectRenderJobSse(
        reconnectJobId,
        reconnectEpoch,
        `reconnect#${nextAttempt}:${reason}`,
      );
    }, delayMs);
  }

  scheduleRenderJobReconnectFromLifecycle = scheduleRenderJobReconnect;

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
      clearRenderJobReconnectTimer();
      renderJobReconnectAttempt = 0;
      if (pollingIntervalId) {
        clearInterval(pollingIntervalId);
        pollingIntervalId = null;
      }
      clearRenderJobHealthCheckInterval();
      lastRenderJobSseActivityAt = 0;

      try {
        const stillSameJob =
          trackedJobId === settledJobId && trackedJobEpoch === settleEpoch;
        if (
          stillSameJob &&
          trackedJobOptions.refreshSessionOnTerminal !== false
        ) {
          const module = await import("./useEditSession");
          const editSession = module.useEditSession();
          await editSession.refreshFormalSessionState();
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

function clearRenderJobReconnectTimer() {
  if (renderJobReconnectTimerId === null) {
    return;
  }
  clearTimeout(renderJobReconnectTimerId);
  renderJobReconnectTimerId = null;
}

function shouldTrackJobLifecycle() {
  return (
    trackedJobId !== null &&
    currentRenderJob.value !== null &&
    !isSettledRenderStatus(currentRenderJob.value.status)
  );
}

function registerRuntimeLifecycleDiagnostics() {
  if (runtimeLifecycleDiagnosticsRegistered) {
    return;
  }
  if (typeof window === "undefined" || typeof document === "undefined") {
    return;
  }

  const reconnectIfNeeded = (event: "visibilitychange" | "pageshow") => {
    if (event === "visibilitychange" && document.visibilityState !== "visible") {
      return;
    }
    if (!shouldTrackJobLifecycle()) {
      return;
    }
    if (unsubscribeSse && sseConnectionState.value === "connected") {
      return;
    }

    console.warn("[useRuntimeState] lifecycle requested render job SSE reconnect", {
      event,
      jobId: trackedJobId,
      sseConnectionState: sseConnectionState.value,
      hasSubscription: unsubscribeSse !== null,
    });
    scheduleRenderJobReconnectFromLifecycle?.("lifecycle:" + event);
  };

  document.addEventListener("visibilitychange", () => {
    reconnectIfNeeded("visibilitychange");
  });
  window.addEventListener("pageshow", () => {
    reconnectIfNeeded("pageshow");
  });
  runtimeLifecycleDiagnosticsRegistered = true;
}
