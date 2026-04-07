import { beforeEach, describe, expect, it, vi } from "vitest";

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
          raw_text: "第一段",
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

    vi.doMock("../src/composables/useEditSession", () => ({
      useEditSession: () => ({
        refreshSnapshot: vi.fn(() => pauseCleanup.promise),
        refreshTimeline: vi.fn(),
        sessionStatus: { value: "ready" },
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
          raw_text: "第一句",
          render_status: "completed",
        },
        {
          segment_id: "seg-2",
          order_key: 2,
          raw_text: "第二句",
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
        renderStatus: "completed",
        renderAssetId: null,
      },
      {
        segmentId: "seg-2",
        orderKey: 2,
        rawText: "第二句",
        renderStatus: "completed",
        renderAssetId: "asset-2",
      },
    ]);
  });

  it("render job 到达 completed 后会清空 currentRenderJob 并重新允许变更", async () => {
    vi.doMock("../src/composables/useEditSession", () => ({
      useEditSession: () => ({
        refreshSnapshot: vi.fn(),
        refreshTimeline: vi.fn(),
        sessionStatus: { value: "ready" },
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
