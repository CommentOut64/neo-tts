import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const {
  editSessionMock,
  playbackMock,
  runtimeStateMock,
  elementPlusMock,
  timelineResponse,
} = vi.hoisted(() => ({
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  ...(() => {
    const { ref } = require("vue");
    return {
  editSessionMock: {
    sessionStatus: ref("ready"),
    refreshFormalSessionState: vi.fn(),
  },
  playbackMock: {
    pauseForProcessing: vi.fn(),
    warmAudioUrls: vi.fn(),
  },
  runtimeStateMock: {
    onRenderJobEvent: vi.fn(),
    onRenderJobCommitted: vi.fn(),
    reconcileTrackedJobTerminal: vi.fn(),
    canMutate: ref(true),
  },
  elementPlusMock: {
    close: vi.fn(),
    info: vi.fn(() => ({ close: vi.fn() })),
    success: vi.fn(),
    error: vi.fn(),
  },
  timelineResponse: {
    timeline_manifest_id: "timeline-2",
    document_id: "doc-1",
    document_version: 2,
    timeline_version: 2,
    sample_rate: 24000,
    playable_sample_span: [0, 100],
    block_entries: [
      {
        block_asset_id: "block-1",
        segment_ids: ["seg-1"],
        start_sample: 0,
        end_sample: 100,
        audio_sample_count: 100,
        audio_url: "/audio/block-1.wav",
      },
      {
        block_asset_id: "block-2",
        segment_ids: ["seg-2"],
        start_sample: 100,
        end_sample: 200,
        audio_sample_count: 100,
        audio_url: "/audio/block-2.wav",
      },
    ],
    segment_entries: [],
    edge_entries: [],
    markers: [],
  },
    };
  })(),
}));

vi.mock("@/composables/useEditSession", () => ({
  useEditSession: () => editSessionMock,
}));

vi.mock("@/composables/usePlayback", () => ({
  usePlayback: () => playbackMock,
}));

vi.mock("@/composables/useRuntimeState", () => ({
  useRuntimeState: () => runtimeStateMock,
  extractCommittedRenderJobPayload: (payload: any) => {
    if (
      typeof payload?.committed_document_version !== "number" ||
      typeof payload?.committed_timeline_manifest_id !== "string"
    ) {
      return null;
    }
    return {
      committed_document_version: payload.committed_document_version,
      committed_timeline_manifest_id: payload.committed_timeline_manifest_id,
      committed_playable_sample_span:
        payload.committed_playable_sample_span ?? null,
      changed_block_asset_ids: Array.isArray(payload.changed_block_asset_ids)
        ? payload.changed_block_asset_ids
        : [],
    };
  },
}));

vi.mock("element-plus", () => ({
  ElMessage: elementPlusMock,
}));

describe("useWorkspaceProcessing", () => {
  beforeEach(async () => {
    vi.resetModules();
    vi.clearAllMocks();
    runtimeStateMock.onRenderJobEvent.mockImplementation(() => () => {});
    runtimeStateMock.onRenderJobCommitted.mockImplementation(() => () => {});
    runtimeStateMock.reconcileTrackedJobTerminal.mockReset();
    runtimeStateMock.reconcileTrackedJobTerminal.mockResolvedValue("completed");
    runtimeStateMock.canMutate.value = true;
    editSessionMock.sessionStatus.value = "ready";
    editSessionMock.refreshFormalSessionState.mockResolvedValue({
      snapshot: {
        document_version: 2,
      },
      timeline: timelineResponse,
    });
    playbackMock.pauseForProcessing.mockImplementation(() => {});
    playbackMock.warmAudioUrls.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("edge 提交会经历 submitting -> processing -> hydrating -> idle，并驱动消息与预热", async () => {
    let runtimeHandler:
      | ((event: { type: string; payload: any; jobId: string | null }) => void)
      | null = null;
    let committedHandler:
      | ((event: { payload: any; jobId: string | null }) => void)
      | null = null;
    runtimeStateMock.onRenderJobEvent.mockImplementation((handler: typeof runtimeHandler) => {
      runtimeHandler = handler;
      return () => {};
    });
    runtimeStateMock.onRenderJobCommitted.mockImplementation((handler: typeof committedHandler) => {
      committedHandler = handler;
      return () => {};
    });

    const { useWorkspaceProcessing } = await import("../src/composables/useWorkspaceProcessing");
    const processing = useWorkspaceProcessing();

    const completion = processing.startEdgeUpdate({
      summary: "停顿 0.30 -> 0.47",
    });
    expect(processing.phase.value).toBe("submitting");
    expect(processing.isInteractionLocked.value).toBe(true);
    expect(playbackMock.pauseForProcessing).toHaveBeenCalledTimes(1);
    expect(elementPlusMock.info).toHaveBeenCalledWith(
      expect.objectContaining({
        message: expect.stringContaining("停顿"),
        duration: 0,
      }),
    );

    processing.acceptJob({
      job: {
        job_id: "job-edge-1",
        document_id: "doc-1",
        status: "queued",
        progress: 0,
        message: "queued",
      },
      jobKind: "edge-compose",
    });
    expect(processing.phase.value).toBe("processing");

    await runtimeHandler?.({
      type: "job_state_changed",
      payload: {
        job_id: "job-edge-1",
        status: "committing",
      },
      jobId: "job-edge-1",
    });
    await committedHandler?.({
      payload: {
        committed_document_version: 2,
        committed_timeline_manifest_id: "timeline-2",
        committed_playable_sample_span: [0, 100],
        changed_block_asset_ids: ["block-2"],
      },
      jobId: "job-edge-1",
    });

    await completion;

    expect(processing.phase.value).toBe("idle");
    expect(processing.isInteractionLocked.value).toBe(false);
    expect(editSessionMock.refreshFormalSessionState).toHaveBeenCalledTimes(1);
    expect(playbackMock.warmAudioUrls).toHaveBeenCalledWith([
      "/audio/block-2.wav",
    ]);
    expect(elementPlusMock.success).toHaveBeenCalledWith(
      expect.objectContaining({
        message: "停顿调整已完成",
      }),
    );
  });

  it("不会再把 completed 当成进入 hydration 的主触发条件", async () => {
    let runtimeHandler:
      | ((event: { type: string; payload: any; jobId: string | null }) => void)
      | null = null;
    let committedHandler:
      | ((event: { payload: any; jobId: string | null }) => void)
      | null = null;
    runtimeStateMock.onRenderJobEvent.mockImplementation((handler: typeof runtimeHandler) => {
      runtimeHandler = handler;
      return () => {};
    });
    runtimeStateMock.onRenderJobCommitted.mockImplementation((handler: typeof committedHandler) => {
      committedHandler = handler;
      return () => {};
    });

    const { useWorkspaceProcessing } = await import("../src/composables/useWorkspaceProcessing");
    const processing = useWorkspaceProcessing();
    const completion = processing.startEdgeUpdate({
      summary: "停顿 0.30 -> 0.47",
    });

    processing.acceptJob({
      job: {
        job_id: "job-edge-2",
        document_id: "doc-1",
        status: "queued",
        progress: 0,
        message: "queued",
      },
      jobKind: "edge-compose",
    });

    await runtimeHandler?.({
      type: "job_state_changed",
      payload: {
        job_id: "job-edge-2",
        status: "completed",
        result_document_version: 2,
      },
      jobId: "job-edge-2",
    });

    await Promise.resolve();

    expect(editSessionMock.refreshFormalSessionState).not.toHaveBeenCalled();
    expect(processing.phase.value).toBe("processing");

    await committedHandler?.({
      payload: {
        committed_document_version: 2,
        committed_timeline_manifest_id: "timeline-2",
        committed_playable_sample_span: [0, 100],
        changed_block_asset_ids: ["block-2"],
      },
      jobId: "job-edge-2",
    });
    await completion;

    expect(editSessionMock.refreshFormalSessionState).toHaveBeenCalledTimes(1);
    expect(playbackMock.warmAudioUrls).toHaveBeenCalledWith([
      "/audio/block-2.wav",
    ]);
    expect(processing.phase.value).toBe("idle");
  });

  it("hydration 卡住时会超时失败并解除交互锁", async () => {
    vi.useFakeTimers();
    let committedHandler:
      | ((event: { payload: any; jobId: string | null }) => void)
      | null = null;
    runtimeStateMock.onRenderJobCommitted.mockImplementation((handler: typeof committedHandler) => {
      committedHandler = handler;
      return () => {};
    });

    playbackMock.warmAudioUrls.mockReturnValue(new Promise(() => {}));

    const { useWorkspaceProcessing } = await import("../src/composables/useWorkspaceProcessing");
    const processing = useWorkspaceProcessing();
    const completion = processing.startEdgeUpdate({
      summary: "停顿 0.30 -> 0.47",
    });

    processing.acceptJob({
      job: {
        job_id: "job-edge-timeout",
        document_id: "doc-1",
        status: "queued",
        progress: 0,
        message: "queued",
      },
      jobKind: "edge-compose",
    });

    void committedHandler?.({
      payload: {
        committed_document_version: 2,
        committed_timeline_manifest_id: "timeline-2",
        committed_playable_sample_span: [0, 100],
        document_version: 2,
        changed_block_asset_ids: ["block-2"],
      },
      jobId: "job-edge-timeout",
    });

    const completionAssertion = expect(completion).rejects.toThrow(
      "准备新音频超时",
    );
    await vi.advanceTimersByTimeAsync(8000);
    await completionAssertion;
    expect(processing.phase.value).toBe("idle");
    expect(processing.isInteractionLocked.value).toBe(false);
    expect(elementPlusMock.error).toHaveBeenCalledWith(
      expect.objectContaining({
        message: "准备新音频超时，请重试",
      }),
    );
  });

  it("即使 processing phase 已 idle，只要仍有活动 render job 也保持交互锁", async () => {
    const { useWorkspaceProcessing } = await import("../src/composables/useWorkspaceProcessing");
    const processing = useWorkspaceProcessing();

    expect(processing.isInteractionLocked.value).toBe(false);

    runtimeStateMock.canMutate.value = false;

    expect(processing.isInteractionLocked.value).toBe(true);
  });

  it("committed hydration 完成后会主动对账 job 终态，避免 SSE 丢失导致页面继续锁死", async () => {
    let committedHandler:
      | ((event: { payload: any; jobId: string | null }) => void)
      | null = null;
    runtimeStateMock.onRenderJobCommitted.mockImplementation((handler: typeof committedHandler) => {
      committedHandler = handler;
      return () => {};
    });

    const { useWorkspaceProcessing } = await import("../src/composables/useWorkspaceProcessing");
    const processing = useWorkspaceProcessing();
    const completion = processing.startEdgeUpdate({
      summary: "停顿 0.30 -> 0.47",
    });

    processing.acceptJob({
      job: {
        job_id: "job-edge-reconcile",
        document_id: "doc-1",
        status: "queued",
        progress: 0,
        message: "queued",
      },
      jobKind: "edge-compose",
    });

    await committedHandler?.({
      payload: {
        committed_document_version: 2,
        committed_timeline_manifest_id: "timeline-2",
        committed_playable_sample_span: [0, 100],
        changed_block_asset_ids: ["block-2"],
      },
      jobId: "job-edge-reconcile",
    });
    await completion;

    expect(runtimeStateMock.reconcileTrackedJobTerminal).toHaveBeenCalledWith(
      "job-edge-reconcile",
    );
  });

  it("瞬时完成时会保证处理中提示至少展示一段时间，再切到完成提示", async () => {
    vi.useFakeTimers();
    let committedHandler:
      | ((event: { payload: any; jobId: string | null }) => void)
      | null = null;
    runtimeStateMock.onRenderJobCommitted.mockImplementation((handler: typeof committedHandler) => {
      committedHandler = handler;
      return () => {};
    });

    const { useWorkspaceProcessing } = await import("../src/composables/useWorkspaceProcessing");
    const processing = useWorkspaceProcessing();
    let resolved = false;
    const completion = processing
      .startEdgeUpdate({
        summary: "停顿 0.30 -> 0.47",
      })
      .then(() => {
        resolved = true;
      });

    processing.acceptJob({
      job: {
        job_id: "job-edge-fast",
        document_id: "doc-1",
        status: "queued",
        progress: 0,
        message: "queued",
      },
      jobKind: "edge-compose",
    });

    await committedHandler?.({
      payload: {
        committed_document_version: 2,
        committed_timeline_manifest_id: "timeline-2",
        committed_playable_sample_span: [0, 100],
        changed_block_asset_ids: ["block-2"],
      },
      jobId: "job-edge-fast",
    });
    await Promise.resolve();
    await Promise.resolve();

    expect(processing.isInteractionLocked.value).toBe(true);
    expect(elementPlusMock.success).not.toHaveBeenCalled();
    expect(resolved).toBe(false);

    await vi.advanceTimersByTimeAsync(1999);
    expect(processing.isInteractionLocked.value).toBe(true);
    expect(elementPlusMock.success).not.toHaveBeenCalled();
    expect(resolved).toBe(false);

    await vi.advanceTimersByTimeAsync(1);
    await completion;

    expect(processing.isInteractionLocked.value).toBe(false);
    expect(elementPlusMock.success).toHaveBeenCalledWith(
      expect.objectContaining({
        message: "停顿调整已完成",
        duration: 2500,
      }),
    );
  });

  it("一次 edge 提交期间只会保留一个 processing message，不会重复创建多条 info 提示", async () => {
    let runtimeHandler:
      | ((event: { type: string; payload: any; jobId: string | null }) => void)
      | null = null;
    let committedHandler:
      | ((event: { payload: any; jobId: string | null }) => void)
      | null = null;
    runtimeStateMock.onRenderJobEvent.mockImplementation((handler: typeof runtimeHandler) => {
      runtimeHandler = handler;
      return () => {};
    });
    runtimeStateMock.onRenderJobCommitted.mockImplementation((handler: typeof committedHandler) => {
      committedHandler = handler;
      return () => {};
    });

    const { useWorkspaceProcessing } = await import("../src/composables/useWorkspaceProcessing");
    const processing = useWorkspaceProcessing();
    const completion = processing.startEdgeUpdate({
      summary: "停顿 0.30 -> 0.47",
    });

    processing.acceptJob({
      job: {
        job_id: "job-edge-single-info",
        document_id: "doc-1",
        status: "queued",
        progress: 0,
        message: "queued",
      },
      jobKind: "edge-compose",
    });

    await runtimeHandler?.({
      type: "job_state_changed",
      payload: {
        job_id: "job-edge-single-info",
        status: "committing",
      },
      jobId: "job-edge-single-info",
    });
    await committedHandler?.({
      payload: {
        committed_document_version: 2,
        committed_timeline_manifest_id: "timeline-2",
        committed_playable_sample_span: [0, 100],
        changed_block_asset_ids: ["block-2"],
      },
      jobId: "job-edge-single-info",
    });
    await completion;

    expect(elementPlusMock.info).toHaveBeenCalledTimes(1);
  });
});
