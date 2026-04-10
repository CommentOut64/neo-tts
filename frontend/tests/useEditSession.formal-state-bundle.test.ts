import { beforeEach, describe, expect, it, vi } from "vitest";

function createDeferred<T>() {
  let resolve: ((value: T) => void) | null = null;
  const promise = new Promise<T>((innerResolve) => {
    resolve = innerResolve;
  });

  return {
    promise,
    resolve(value: T) {
      resolve?.(value);
    },
  };
}

const {
  apiMock,
  runtimeStateMock,
  timelineMock,
  inputDraftMock,
  draftPersistenceMock,
  lightEditMock,
} = vi.hoisted(() => {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { ref } = require("vue");

  return {
    apiMock: {
      deleteSession: vi.fn(),
      getGroups: vi.fn(),
      getRenderProfiles: vi.fn(),
      getSnapshot: vi.fn(),
      getTimeline: vi.fn(),
      getVoiceBindings: vi.fn(),
      initializeSession: vi.fn(),
      listEdges: vi.fn(),
      listSegments: vi.fn(),
    },
    runtimeStateMock: {
      trackJob: vi.fn(),
    },
    timelineMock: {
      setTimeline: vi.fn(),
    },
    inputDraftMock: {
      text: ref(""),
      source: ref("manual"),
      isEmpty: ref(true),
      draftRevision: ref(0),
      lastSentToSessionRevision: ref(null),
      backfillFromAppliedText: vi.fn(),
      markSentToSession: vi.fn(),
      rememberLastSessionInitialText: vi.fn(),
      handoffFromWorkspace: vi.fn(),
      setText: vi.fn(),
    },
    draftPersistenceMock: {
      clearSnapshot: vi.fn(),
    },
    lightEditMock: {
      clearAll: vi.fn(),
    },
  };
});

vi.mock("@/api/editSession", () => apiMock);
vi.mock("../src/composables/useRuntimeState", () => ({
  useRuntimeState: () => runtimeStateMock,
}));
vi.mock("../src/composables/useTimeline", () => ({
  useTimeline: () => timelineMock,
}));
vi.mock("../src/composables/useInputDraft", () => ({
  useInputDraft: () => inputDraftMock,
}));
vi.mock("../src/composables/useWorkspaceDraftPersistence", () => ({
  useWorkspaceDraftPersistence: () => draftPersistenceMock,
}));
vi.mock("../src/composables/useWorkspaceLightEdit", () => ({
  useWorkspaceLightEdit: () => lightEditMock,
}));

function createReadySnapshot(documentVersion: number, profileId: string, bindingId: string) {
  return {
    session_status: "ready" as const,
    document_id: "doc-1",
    document_version: documentVersion,
    total_segment_count: 1,
    active_job: null,
    segments: [
      {
        raw_text: `正文-${documentVersion}`,
      },
    ],
    default_render_profile_id: profileId,
    default_voice_binding_id: bindingId,
  };
}

function createTimeline(documentVersion: number, timelineId: string, segmentId: string) {
  return {
    timeline_manifest_id: timelineId,
    document_id: "doc-1",
    document_version: documentVersion,
    timeline_version: documentVersion,
    sample_rate: 24000,
    playable_sample_span: [0, 100],
    block_entries: [],
    segment_entries: [
      {
        segment_id: segmentId,
        order_key: 1,
        start_sample: 0,
        end_sample: 100,
        render_status: "ready",
        group_id: null,
        render_profile_id: `profile-${documentVersion}`,
        voice_binding_id: `binding-${documentVersion}`,
      },
    ],
    edge_entries: [],
    markers: [],
  };
}

function createSegment(documentVersion: number, segmentId: string) {
  return {
    segment_id: segmentId,
    document_id: "doc-1",
    order_key: 1,
    previous_segment_id: null,
    next_segment_id: null,
    segment_kind: "speech" as const,
    raw_text: `第 ${documentVersion} 版`,
    normalized_text: `第 ${documentVersion} 版`,
    text_language: "zh",
    render_version: documentVersion,
    render_asset_id: `asset-${documentVersion}`,
    group_id: null,
    render_profile_id: `profile-${documentVersion}`,
    voice_binding_id: `binding-${documentVersion}`,
    render_status: "ready" as const,
    segment_revision: documentVersion,
    effective_duration_samples: 100,
    inference_override: {},
    risk_flags: [],
    assembled_audio_span: [0, 100] as [number, number],
  };
}

function createEdge(documentVersion: number) {
  return {
    edge_id: `edge-${documentVersion}`,
    document_id: "doc-1",
    left_segment_id: `seg-${documentVersion}`,
    right_segment_id: `seg-${documentVersion + 1}`,
    pause_duration_seconds: 0.35 + documentVersion * 0.01,
    boundary_strategy: "crossfade",
    boundary_strategy_locked: false,
    effective_boundary_strategy: "crossfade",
    pause_sample_count: 20,
    boundary_sample_count: 4,
    edge_status: "ready" as const,
    edge_version: documentVersion,
  };
}

function createRenderProfile(documentVersion: number) {
  return {
    render_profile_id: `profile-${documentVersion}`,
    scope: "session" as const,
    name: `profile-${documentVersion}`,
    speed: 1 + documentVersion * 0.1,
    top_k: 10 + documentVersion,
    top_p: 0.9,
    temperature: 1,
    noise_scale: 0.35,
    reference_audio_path: null,
    reference_text: `参考-${documentVersion}`,
    reference_language: "zh",
    extra_overrides: {},
  };
}

function createVoiceBinding(documentVersion: number) {
  return {
    voice_binding_id: `binding-${documentVersion}`,
    scope: "session" as const,
    voice_id: `voice-${documentVersion}`,
    model_key: `voice-${documentVersion}`,
    gpt_path: `voice-${documentVersion}.ckpt`,
    sovits_path: `voice-${documentVersion}.pth`,
    speaker_meta: {},
  };
}

describe("useEditSession formal state bundle", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    inputDraftMock.text.value = "";
    inputDraftMock.source.value = "manual";
    inputDraftMock.isEmpty.value = true;
    inputDraftMock.draftRevision.value = 0;
    inputDraftMock.lastSentToSessionRevision.value = null;
  });

  it("refreshFormalSessionState 在资源未齐前不会暴露半刷新状态", async () => {
    const { useEditSession } = await import("../src/composables/useEditSession");
    const editSession = useEditSession();

    editSession.sessionStatus.value = "ready";
    editSession.snapshot.value = createReadySnapshot(1, "profile-1", "binding-1");
    editSession.timeline.value = createTimeline(1, "timeline-1", "seg-1");
    editSession.segments.value = [createSegment(1, "seg-1")];
    editSession.segmentsLoaded.value = true;
    editSession.edges.value = [createEdge(1)];
    editSession.edgesLoaded.value = true;
    editSession.groups.value = [];
    editSession.renderProfiles.value = [createRenderProfile(1)];
    editSession.voiceBindings.value = [createVoiceBinding(1)];
    editSession.sessionResourcesLoaded.value = true;

    const snapshotDeferred = createDeferred(createReadySnapshot(2, "profile-2", "binding-2"));
    const timelineDeferred = createDeferred(createTimeline(2, "timeline-2", "seg-2"));
    const segmentsDeferred = createDeferred({
      document_id: "doc-1",
      document_version: 2,
      items: [createSegment(2, "seg-2")],
      next_cursor: null,
    });
    const edgesDeferred = createDeferred({
      document_id: "doc-1",
      document_version: 2,
      items: [createEdge(2)],
      next_cursor: null,
    });
    const groupsDeferred = createDeferred({
      document_id: "doc-1",
      document_version: 2,
      items: [],
    });
    const profilesDeferred = createDeferred({
      document_id: "doc-1",
      document_version: 2,
      items: [createRenderProfile(2)],
    });
    const bindingsDeferred = createDeferred({
      document_id: "doc-1",
      document_version: 2,
      items: [createVoiceBinding(2)],
    });

    apiMock.getSnapshot.mockReturnValueOnce(snapshotDeferred.promise);
    apiMock.getTimeline.mockReturnValueOnce(timelineDeferred.promise);
    apiMock.listSegments.mockReturnValueOnce(segmentsDeferred.promise);
    apiMock.listEdges.mockReturnValueOnce(edgesDeferred.promise);
    apiMock.getGroups.mockReturnValueOnce(groupsDeferred.promise);
    apiMock.getRenderProfiles.mockReturnValueOnce(profilesDeferred.promise);
    apiMock.getVoiceBindings.mockReturnValueOnce(bindingsDeferred.promise);

    const refreshPromise = editSession.refreshFormalSessionState();

    snapshotDeferred.resolve(createReadySnapshot(2, "profile-2", "binding-2"));
    timelineDeferred.resolve(createTimeline(2, "timeline-2", "seg-2"));
    await Promise.resolve();
    await Promise.resolve();

    expect(editSession.snapshot.value?.document_version).toBe(1);
    expect(editSession.timeline.value?.timeline_manifest_id).toBe("timeline-1");
    expect(editSession.renderProfiles.value[0]?.render_profile_id).toBe("profile-1");
    expect(editSession.voiceBindings.value[0]?.voice_binding_id).toBe("binding-1");

    segmentsDeferred.resolve({
      document_id: "doc-1",
      document_version: 2,
      items: [createSegment(2, "seg-2")],
      next_cursor: null,
    });
    edgesDeferred.resolve({
      document_id: "doc-1",
      document_version: 2,
      items: [createEdge(2)],
      next_cursor: null,
    });
    groupsDeferred.resolve({
      document_id: "doc-1",
      document_version: 2,
      items: [],
    });
    profilesDeferred.resolve({
      document_id: "doc-1",
      document_version: 2,
      items: [createRenderProfile(2)],
    });
    bindingsDeferred.resolve({
      document_id: "doc-1",
      document_version: 2,
      items: [createVoiceBinding(2)],
    });

    await refreshPromise;

    expect(editSession.snapshot.value?.document_version).toBe(2);
    expect(editSession.timeline.value?.timeline_manifest_id).toBe("timeline-2");
    expect(editSession.renderProfiles.value[0]?.render_profile_id).toBe("profile-2");
    expect(editSession.voiceBindings.value[0]?.voice_binding_id).toBe("binding-2");
    expect(timelineMock.setTimeline).toHaveBeenCalledWith(
      expect.objectContaining({ timeline_manifest_id: "timeline-2" }),
    );
  });

  it("旧的 formal refresh 晚到时不会覆盖更新的正式状态", async () => {
    const { useEditSession } = await import("../src/composables/useEditSession");
    const editSession = useEditSession();

    editSession.sessionStatus.value = "ready";
    editSession.snapshot.value = createReadySnapshot(1, "profile-1", "binding-1");
    editSession.timeline.value = createTimeline(1, "timeline-1", "seg-1");
    editSession.segments.value = [createSegment(1, "seg-1")];
    editSession.segmentsLoaded.value = true;
    editSession.edges.value = [createEdge(1)];
    editSession.edgesLoaded.value = true;
    editSession.renderProfiles.value = [createRenderProfile(1)];
    editSession.voiceBindings.value = [createVoiceBinding(1)];
    editSession.sessionResourcesLoaded.value = true;

    const firstSegmentsDeferred = createDeferred({
      document_id: "doc-1",
      document_version: 2,
      items: [createSegment(2, "seg-2")],
      next_cursor: null,
    });
    const firstEdgesDeferred = createDeferred({
      document_id: "doc-1",
      document_version: 2,
      items: [createEdge(2)],
      next_cursor: null,
    });
    const firstProfilesDeferred = createDeferred({
      document_id: "doc-1",
      document_version: 2,
      items: [createRenderProfile(2)],
    });
    const firstBindingsDeferred = createDeferred({
      document_id: "doc-1",
      document_version: 2,
      items: [createVoiceBinding(2)],
    });

    apiMock.getSnapshot
      .mockResolvedValueOnce(createReadySnapshot(2, "profile-2", "binding-2"))
      .mockResolvedValueOnce(createReadySnapshot(3, "profile-3", "binding-3"));
    apiMock.getTimeline
      .mockResolvedValueOnce(createTimeline(2, "timeline-2", "seg-2"))
      .mockResolvedValueOnce(createTimeline(3, "timeline-3", "seg-3"));
    apiMock.listSegments
      .mockReturnValueOnce(firstSegmentsDeferred.promise)
      .mockResolvedValueOnce({
        document_id: "doc-1",
        document_version: 3,
        items: [createSegment(3, "seg-3")],
        next_cursor: null,
      });
    apiMock.listEdges
      .mockReturnValueOnce(firstEdgesDeferred.promise)
      .mockResolvedValueOnce({
        document_id: "doc-1",
        document_version: 3,
        items: [createEdge(3)],
        next_cursor: null,
      });
    apiMock.getGroups
      .mockResolvedValueOnce({
        document_id: "doc-1",
        document_version: 2,
        items: [],
      })
      .mockResolvedValueOnce({
        document_id: "doc-1",
        document_version: 3,
        items: [],
      });
    apiMock.getRenderProfiles
      .mockReturnValueOnce(firstProfilesDeferred.promise)
      .mockResolvedValueOnce({
        document_id: "doc-1",
        document_version: 3,
        items: [createRenderProfile(3)],
      });
    apiMock.getVoiceBindings
      .mockReturnValueOnce(firstBindingsDeferred.promise)
      .mockResolvedValueOnce({
        document_id: "doc-1",
        document_version: 3,
        items: [createVoiceBinding(3)],
      });

    const firstRefresh = editSession.refreshFormalSessionState();
    const secondRefresh = editSession.refreshFormalSessionState();

    await secondRefresh;

    expect(editSession.snapshot.value?.document_version).toBe(3);
    expect(editSession.renderProfiles.value[0]?.render_profile_id).toBe("profile-3");
    expect(editSession.voiceBindings.value[0]?.voice_binding_id).toBe("binding-3");

    firstSegmentsDeferred.resolve({
      document_id: "doc-1",
      document_version: 2,
      items: [createSegment(2, "seg-2")],
      next_cursor: null,
    });
    firstEdgesDeferred.resolve({
      document_id: "doc-1",
      document_version: 2,
      items: [createEdge(2)],
      next_cursor: null,
    });
    firstProfilesDeferred.resolve({
      document_id: "doc-1",
      document_version: 2,
      items: [createRenderProfile(2)],
    });
    firstBindingsDeferred.resolve({
      document_id: "doc-1",
      document_version: 2,
      items: [createVoiceBinding(2)],
    });

    await firstRefresh;

    expect(editSession.snapshot.value?.document_version).toBe(3);
    expect(editSession.timeline.value?.timeline_manifest_id).toBe("timeline-3");
    expect(editSession.renderProfiles.value[0]?.render_profile_id).toBe("profile-3");
    expect(editSession.voiceBindings.value[0]?.voice_binding_id).toBe("binding-3");
  });
});
