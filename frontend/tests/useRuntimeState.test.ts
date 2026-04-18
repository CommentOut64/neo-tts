import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const subscribeRenderJobEvents = vi.fn(() => () => {});
const getRenderJob = vi.fn();
const pauseRenderJob = vi.fn();
const cancelRenderJob = vi.fn();
const resumeRenderJob = vi.fn();
const subscribeExportJobEvents = vi.fn(() => () => {});
const getExportJob = vi.fn();

vi.mock("@/api/editSession", () => ({
  subscribeRenderJobEvents,
  getRenderJob,
  pauseRenderJob,
  cancelRenderJob,
  resumeRenderJob,
  subscribeExportJobEvents,
  getExportJob,
}));

function createDeferred() {
  let resolve: (() => void) | null = null;
  const promise = new Promise<void>((innerResolve) => {
    resolve = innerResolve;
  });

  return {
    promise,
    resolve: () => {
      resolve?.();
    },
  };
}

describe("useRuntimeState", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.resetModules();
    subscribeRenderJobEvents.mockClear();
    getRenderJob.mockReset();
    pauseRenderJob.mockReset();
    cancelRenderJob.mockReset();
    resumeRenderJob.mockReset();
    subscribeExportJobEvents.mockReset();
    subscribeExportJobEvents.mockImplementation(() => () => {});
    getExportJob.mockReset();
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
  });

  it("trackJob 会立即建立运行态门禁并锁定当前段", async () => {
    const { useRuntimeState } = await import("../src/composables/useRuntimeState");
    const runtimeState = useRuntimeState();

    runtimeState.trackJob(
      {
        job_id: "job-1",
        document_id: "doc-1",
        status: "queued",
        progress: 0,
        message: "queued",
      },
      {
        initialRendering: false,
        lockedSegmentIds: ["seg-1"],
        refreshSessionOnTerminal: false,
      },
    );

    expect(runtimeState.currentRenderJob.value?.job_id).toBe("job-1");
    expect(runtimeState.canMutate.value).toBe(false);
    expect(Array.from(runtimeState.lockedSegmentIds.value)).toEqual(["seg-1"]);
    expect(runtimeState.isInitialRendering.value).toBe(false);
    expect(subscribeRenderJobEvents).toHaveBeenCalledWith(
      "job-1",
      expect.any(Object),
    );
  });

  it("pause 后调用 resumeJob 会使用新 job id 重新跟踪", async () => {
    const { useRuntimeState } = await import("../src/composables/useRuntimeState");
    const runtimeState = useRuntimeState();

    subscribeRenderJobEvents.mockImplementation(() => () => {});

    runtimeState.trackJob(
      {
        job_id: "job-paused",
        document_id: "doc-1",
        status: "queued",
        progress: 0.2,
        message: "queued",
      },
      {
        initialRendering: true,
        lockedSegmentIds: ["seg-2"],
        refreshSessionOnTerminal: false,
      },
    );

    const firstHandler = subscribeRenderJobEvents.mock.calls[0][1];
    await firstHandler.onEvent("segments_initialized", {
      document_id: "doc-1",
      document_version: 1,
      segments: [
        {
          segment_id: "seg-1",
          order_key: 1,
          display_text: "第一段",
          render_status: "completed",
        },
      ],
    });
    await firstHandler.onEvent("job_state_changed", {
      job_id: "job-paused",
      document_id: "doc-1",
      status: "paused",
      progress: 0.4,
      message: "paused",
    });

    resumeRenderJob.mockResolvedValue({
      job_id: "job-resumed",
      document_id: "doc-1",
      status: "queued",
      progress: 0,
      message: "resumed",
    });

    await runtimeState.resumeJob();

    expect(resumeRenderJob).toHaveBeenCalledWith("job-paused");
    expect(runtimeState.currentRenderJob.value?.job_id).toBe("job-resumed");
    expect(runtimeState.currentRenderJob.value?.progress).toBe(0.4);
    expect(runtimeState.currentRenderJob.value?.message).toBe("resumed");
    expect(runtimeState.isInitialRendering.value).toBe(true);
    expect(Array.from(runtimeState.lockedSegmentIds.value)).toEqual(["seg-2"]);
    expect(runtimeState.progressiveSegments.value).toEqual([
      {
        segmentId: "seg-1",
        orderKey: 1,
        rawText: "第一段",
        displayText: "第一段",
        renderStatus: "completed",
        renderAssetId: null,
      },
    ]);
    expect(subscribeRenderJobEvents).toHaveBeenLastCalledWith(
      "job-resumed",
      expect.any(Object),
    );
  });

  it("暂停与恢复事件会替换成更易懂的提示文案", async () => {
    const { useRuntimeState } = await import("../src/composables/useRuntimeState");
    const runtimeState = useRuntimeState();

    subscribeRenderJobEvents.mockImplementation(() => () => {});

    runtimeState.trackJob(
      {
        job_id: "job-friendly",
        document_id: "doc-1",
        status: "rendering",
        progress: 0.3,
        message: "technical",
      },
      {
        initialRendering: true,
        refreshSessionOnTerminal: false,
      },
    );

    const handler = subscribeRenderJobEvents.mock.calls[0][1];

    await handler.onEvent("job_paused", {
      job_id: "job-friendly",
    });

    expect(runtimeState.currentRenderJob.value?.status).toBe("paused");
    expect(runtimeState.currentRenderJob.value?.message).toBe("已暂停，随时可以继续");

    resumeRenderJob.mockResolvedValue({
      job_id: "job-friendly-resumed",
      document_id: "doc-1",
      status: "queued",
      progress: 0,
      message: "resumed-raw",
    });

    await runtimeState.resumeJob();

    const resumedHandler = subscribeRenderJobEvents.mock.calls[1][1];
    await resumedHandler.onEvent("job_resumed", {
      source_job_id: "job-friendly",
      checkpoint_id: "checkpoint-1",
      remaining_segment_ids: ["seg-1"],
    });

    expect(runtimeState.currentRenderJob.value?.message).toBe("已继续，正在接着处理剩余内容");
  });

  it("pause 收尾尚未结束时恢复，不会被旧收尾清空新 job 的渐进状态", async () => {
    const pauseCleanup = createDeferred();
    const refreshFormalSessionState = vi.fn(() => pauseCleanup.promise);

    vi.doMock("../src/composables/useEditSession", () => ({
      useEditSession: () => ({
        refreshFormalSessionState,
      }),
    }));

    const { useRuntimeState } = await import("../src/composables/useRuntimeState");
    const runtimeState = useRuntimeState();

    subscribeRenderJobEvents.mockImplementation(() => () => {});

    runtimeState.trackJob(
      {
        job_id: "job-paused",
        document_id: "doc-1",
        status: "rendering",
        progress: 0.5,
        message: "paused-halfway",
      },
      {
        initialRendering: true,
        lockedSegmentIds: ["seg-2"],
      },
    );

    const firstHandler = subscribeRenderJobEvents.mock.calls[0][1];

    await firstHandler.onEvent("segments_initialized", {
      document_id: "doc-1",
      document_version: 1,
      segments: [
        {
          segment_id: "seg-1",
          order_key: 1,
          display_text: "第一句",
          render_status: "completed",
        },
        {
          segment_id: "seg-2",
          order_key: 2,
          display_text: "第二句",
          render_status: "pending",
        },
      ],
    });

    await firstHandler.onEvent("job_state_changed", {
      job_id: "job-paused",
      document_id: "doc-1",
      status: "paused",
      progress: 0.5,
      message: "paused",
    });

    resumeRenderJob.mockResolvedValue({
      job_id: "job-resumed",
      document_id: "doc-1",
      status: "queued",
      progress: 0,
      message: "resumed",
    });

    await runtimeState.resumeJob();

    const resumedHandler = subscribeRenderJobEvents.mock.calls[1][1];

    await resumedHandler.onEvent("job_resumed", {
      source_job_id: "job-paused",
      checkpoint_id: "checkpoint-1",
      remaining_segment_ids: ["seg-2"],
    });
    await resumedHandler.onEvent("job_state_changed", {
      job_id: "job-resumed",
      document_id: "doc-1",
      status: "rendering",
      progress: 0.1,
      message: "继续推理",
    });

    expect(runtimeState.currentRenderJob.value?.progress).toBe(0.5);
    expect(runtimeState.isInitialRendering.value).toBe(true);
    expect(Array.from(runtimeState.lockedSegmentIds.value)).toEqual(["seg-2"]);

    pauseCleanup.resolve();
    await Promise.resolve();
    await Promise.resolve();

    expect(runtimeState.isInitialRendering.value).toBe(true);
    expect(runtimeState.progressiveSegments.value).toHaveLength(2);

    await resumedHandler.onEvent("segment_completed", {
      segment_id: "seg-2",
      order_key: 2,
      render_asset_id: "asset-2",
      render_status: "completed",
      effective_duration_samples: 100,
    });
    await resumedHandler.onEvent("job_state_changed", {
      job_id: "job-resumed",
      document_id: "doc-1",
      status: "rendering",
      progress: 0.75,
      message: "已完成第 2 段",
    });

    expect(runtimeState.currentRenderJob.value?.progress).toBe(0.75);
    expect(runtimeState.progressiveSegments.value).toEqual([
      {
        segmentId: "seg-1",
        orderKey: 1,
        rawText: "第一句",
        displayText: "第一句",
        renderStatus: "completed",
        renderAssetId: null,
      },
      {
        segmentId: "seg-2",
        orderKey: 2,
        rawText: "第二句",
        displayText: "第二句",
        renderStatus: "completed",
        renderAssetId: "asset-2",
      },
    ]);
  });

  it("segments_initialized 会同时映射用户可见 displayText", async () => {
    const { useRuntimeState } = await import("../src/composables/useRuntimeState");
    const runtimeState = useRuntimeState();

    subscribeRenderJobEvents.mockImplementation(() => () => {});

    runtimeState.trackJob(
      {
        job_id: "job-display",
        document_id: "doc-1",
        status: "queued",
        progress: 0,
        message: "queued",
      },
      {
        initialRendering: true,
        refreshSessionOnTerminal: false,
      },
    );

    const handler = subscribeRenderJobEvents.mock.calls[0][1];

    await handler.onEvent("segments_initialized", {
      document_id: "doc-1",
      document_version: 1,
      segments: [
        {
          segment_id: "seg-1",
          order_key: 1,
          stem: "Hello world",
          display_text: "Hello world.",
          terminal_raw: "",
          terminal_closer_suffix: "",
          terminal_source: "synthetic",
          detected_language: "en",
          render_status: "completed",
        },
      ],
    });

    expect(runtimeState.progressiveSegments.value[0]).toMatchObject({
      rawText: "Hello world.",
      displayText: "Hello world.",
    });
  });

  it("render job 到达 completed 后会清空 currentRenderJob 并重新允许变更", async () => {
    vi.doMock("../src/composables/useEditSession", () => ({
      useEditSession: () => ({
        refreshFormalSessionState: vi.fn(),
      }),
    }));

    const { useRuntimeState } = await import("../src/composables/useRuntimeState");
    const runtimeState = useRuntimeState();

    runtimeState.trackJob(
      {
        job_id: "job-finished",
        document_id: "doc-1",
        status: "rendering",
        progress: 0.5,
        message: "running",
      },
      { refreshSessionOnTerminal: false },
    );

    const handler = subscribeRenderJobEvents.mock.calls[0][1];
    await handler.onEvent("job_state_changed", {
      job_id: "job-finished",
      document_id: "doc-1",
      status: "completed",
      progress: 1,
      message: "done",
    });
    await Promise.resolve();
    await Promise.resolve();

    expect(runtimeState.currentRenderJob.value).toBeNull();
    expect(runtimeState.canMutate.value).toBe(true);
  });

  it("render job 终态需要刷新正式状态时，会走 refreshFormalSessionState", async () => {
    const refreshFormalSessionState = vi.fn().mockResolvedValue(undefined);

    vi.doMock("../src/composables/useEditSession", () => ({
      useEditSession: () => ({
        refreshFormalSessionState,
      }),
    }));

    const { useRuntimeState } = await import("../src/composables/useRuntimeState");
    const runtimeState = useRuntimeState();

    runtimeState.trackJob(
      {
        job_id: "job-refresh-formal",
        document_id: "doc-1",
        status: "rendering",
        progress: 0.4,
        message: "running",
      },
      {
        initialRendering: false,
      },
    );

    const handler = subscribeRenderJobEvents.mock.calls[0][1];
    await handler.onEvent("job_state_changed", {
      job_id: "job-refresh-formal",
      document_id: "doc-1",
      status: "completed",
      progress: 1,
      message: "done",
    });
    await vi.waitFor(() => {
      expect(refreshFormalSessionState).toHaveBeenCalledTimes(1);
    });
  });

  it("render job SSE 断线后会先尝试自动重连，而不是立刻退回 polling", async () => {
    const firstUnsubscribe = vi.fn();
    const secondUnsubscribe = vi.fn();
    subscribeRenderJobEvents
      .mockReturnValueOnce(firstUnsubscribe)
      .mockReturnValueOnce(secondUnsubscribe);

    const { useRuntimeState } = await import("../src/composables/useRuntimeState");
    const runtimeState = useRuntimeState();

    runtimeState.trackJob(
      {
        job_id: "job-reconnect",
        document_id: "doc-1",
        status: "rendering",
        progress: 0.2,
        message: "running",
      },
      {
        initialRendering: true,
        refreshSessionOnTerminal: false,
      },
    );

    const firstHandler = subscribeRenderJobEvents.mock.calls[0][1];
    firstHandler.onError?.(new Error("boom"));

    expect(firstUnsubscribe).toHaveBeenCalledTimes(1);
    expect(runtimeState.sseConnectionState.value).toBe("disconnected");
    expect(getRenderJob).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(500);

    expect(subscribeRenderJobEvents).toHaveBeenCalledTimes(2);
    expect(getRenderJob).not.toHaveBeenCalled();

    const secondHandler = subscribeRenderJobEvents.mock.calls[1][1];
    secondHandler.onOpen?.();

    expect(runtimeState.sseConnectionState.value).toBe("connected");
  });

  it("会向外广播 render job SSE 事件，供 workspace processing 消费", async () => {
    const { useRuntimeState } = await import("../src/composables/useRuntimeState");
    const runtimeState = useRuntimeState();
    const listener = vi.fn();

    runtimeState.trackJob(
      {
        job_id: "job-events",
        document_id: "doc-1",
        status: "rendering",
        progress: 0.2,
        message: "running",
      },
      { refreshSessionOnTerminal: false },
    );

    const unsubscribe = runtimeState.onRenderJobEvent(listener);
    const handler = subscribeRenderJobEvents.mock.calls[0][1];

    await handler.onEvent("timeline_committed", {
      document_version: 2,
      timeline_manifest_id: "timeline-2",
    });

    expect(listener).toHaveBeenCalledWith({
      type: "timeline_committed",
      payload: {
        document_version: 2,
        timeline_manifest_id: "timeline-2",
      },
      jobId: "job-events",
    });

    unsubscribe();
  });

  it("会把 job committed 元数据归一化后只广播一次，即使同时收到 timeline_committed 与 job_state_changed", async () => {
    const { useRuntimeState } = await import("../src/composables/useRuntimeState");
    const runtimeState = useRuntimeState();
    const listener = vi.fn();

    runtimeState.trackJob(
      {
        job_id: "job-committed",
        document_id: "doc-1",
        status: "committing",
        progress: 0.9,
        message: "committing",
      },
      { refreshSessionOnTerminal: false },
    );

    runtimeState.onRenderJobCommitted(listener);
    const handler = subscribeRenderJobEvents.mock.calls[0][1];

    await handler.onEvent("job_state_changed", {
      job_id: "job-committed",
      document_id: "doc-1",
      status: "committing",
      progress: 0.95,
      message: "committing",
      committed_document_version: 2,
      committed_timeline_manifest_id: "timeline-2",
      committed_playable_sample_span: [0, 100],
      changed_block_asset_ids: ["block-2"],
    });
    await handler.onEvent("timeline_committed", {
      document_version: 2,
      timeline_manifest_id: "timeline-2",
      playable_sample_span: [0, 100],
      changed_block_asset_ids: ["block-2"],
    });

    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenCalledWith({
      jobId: "job-committed",
      payload: {
        committed_document_version: 2,
        committed_timeline_manifest_id: "timeline-2",
        committed_playable_sample_span: [0, 100],
        changed_block_asset_ids: ["block-2"],
      },
    });
    expect(runtimeState.currentRenderJob.value).toMatchObject({
      committed_document_version: 2,
      committed_timeline_manifest_id: "timeline-2",
      changed_block_asset_ids: ["block-2"],
    });
  });

  it("可以主动对账已跟踪 job 的终态，避免 terminal SSE 丢失后一直锁死", async () => {
    vi.doMock("../src/composables/useEditSession", () => ({
      useEditSession: () => ({
        refreshFormalSessionState: vi.fn(),
      }),
    }));

    const { useRuntimeState } = await import("../src/composables/useRuntimeState");
    const runtimeState = useRuntimeState();

    runtimeState.trackJob(
      {
        job_id: "job-reconcile",
        document_id: "doc-1",
        status: "committing",
        progress: 0.9,
        message: "committing",
      },
      { refreshSessionOnTerminal: false },
    );

    getRenderJob.mockResolvedValue({
      job_id: "job-reconcile",
      document_id: "doc-1",
      status: "completed",
      progress: 1,
      message: "done",
      committed_document_version: 2,
      committed_timeline_manifest_id: "timeline-2",
      committed_playable_sample_span: [0, 100],
      changed_block_asset_ids: ["block-2"],
    });

    await runtimeState.reconcileTrackedJobTerminal("job-reconcile");
    await Promise.resolve();
    await Promise.resolve();

    expect(getRenderJob).toHaveBeenCalledWith("job-reconcile");
    expect(runtimeState.currentRenderJob.value).toBeNull();
    expect(runtimeState.canMutate.value).toBe(true);
  });

  it("trackExportJob 会跟踪导出进度并在终态后清空 currentExportJob", async () => {
    const { useRuntimeState } = await import("../src/composables/useRuntimeState");
    const runtimeState = useRuntimeState();

    runtimeState.trackExportJob({
      export_job_id: "export-1",
      document_id: "doc-1",
      document_version: 2,
      timeline_manifest_id: "timeline-1",
      export_kind: "segments",
      status: "queued",
      target_dir: "exports/demo",
      overwrite_policy: "fail",
      progress: 0,
      message: "queued",
      output_manifest: null,
      staging_dir: null,
      updated_at: "2026-04-07T00:00:00Z",
    });

    expect(runtimeState.currentExportJob.value?.export_job_id).toBe("export-1");

    const handler = subscribeExportJobEvents.mock.calls[0][1];
    handler.onProgress?.(0.5, "halfway");

    expect(runtimeState.currentExportJob.value?.progress).toBe(0.5);
    expect(runtimeState.currentExportJob.value?.message).toBe("halfway");

    handler.onCompleted?.({
      export_job_id: "export-1",
      document_id: "doc-1",
      document_version: 2,
      timeline_manifest_id: "timeline-1",
      export_kind: "segments",
      status: "completed",
      target_dir: "exports/demo",
      overwrite_policy: "fail",
      progress: 1,
      message: "done",
      output_manifest: null,
      staging_dir: null,
      updated_at: "2026-04-07T00:00:00Z",
    });

    expect(runtimeState.currentExportJob.value).toBeNull();
  });
});
