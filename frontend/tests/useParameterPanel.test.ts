import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

const {
  editSessionMock,
  runtimeStateMock,
  apiMock,
  processingMock,
  elementPlusMock,
} = vi.hoisted(() => ({
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  ...(() => {
    const { ref } = require("vue");
    return {
  editSessionMock: {
    sessionStatus: ref("ready"),
    formalStateStatus: ref("ready"),
    snapshot: ref({
      session_status: "ready",
      document_id: "doc-1",
      document_version: 1,
      total_segment_count: 2,
      active_job: null,
      segments: [],
      default_render_profile_id: "profile-session",
      default_voice_binding_id: "binding-session",
    }),
    segments: ref([
      {
        segment_id: "seg-1",
        document_id: "doc-1",
        order_key: 1,
        previous_segment_id: null,
        next_segment_id: "seg-2",
        segment_kind: "speech",
        raw_text: "第一句。",
        normalized_text: "第一句。",
        text_language: "zh",
        render_version: 1,
        render_asset_id: "render-seg-1",
        group_id: null,
        render_profile_id: "profile-seg-1",
        voice_binding_id: "binding-seg-1",
        render_status: "ready",
        segment_revision: 1,
        effective_duration_samples: 50,
        inference_override: {},
        risk_flags: [],
        assembled_audio_span: [0, 50],
      },
    ]),
    groups: ref([]),
    timeline: ref({
      timeline_manifest_id: "timeline-1",
      document_id: "doc-1",
      document_version: 1,
      timeline_version: 1,
      sample_rate: 24000,
      playable_sample_span: [0, 100],
      block_entries: [],
      segment_entries: [
        {
          segment_id: "seg-1",
          order_key: 1,
          start_sample: 0,
          end_sample: 50,
          render_status: "ready",
          group_id: null,
          render_profile_id: "profile-seg-1",
          voice_binding_id: "binding-seg-1",
        },
      ],
      edge_entries: [],
      markers: [],
    }),
    renderProfiles: ref([
      {
        render_profile_id: "profile-session",
        scope: "session",
        name: "session",
        speed: 1,
        top_k: 15,
        top_p: 1,
        temperature: 1,
        noise_scale: 0.35,
        reference_overrides_by_binding: {},
        reference_audio_path: null,
        reference_text: null,
        reference_language: null,
        extra_overrides: {},
      },
      {
        render_profile_id: "profile-seg-1",
        scope: "segment",
        name: "segment",
        speed: 1.2,
        top_k: 20,
        top_p: 0.8,
        temperature: 0.9,
        noise_scale: 0.4,
        reference_overrides_by_binding: {
          "voice-a:voice-a": {
            reference_audio_path: "seg.wav",
            reference_text: "单段自定义",
            reference_language: "en",
          },
        },
        reference_audio_path: null,
        reference_text: null,
        reference_language: null,
        extra_overrides: {},
      },
    ]),
    voiceBindings: ref([
      {
        voice_binding_id: "binding-session",
        scope: "session",
        voice_id: "voice-default",
        model_key: "voice-default",
        gpt_path: "default.ckpt",
        sovits_path: "default.pth",
        speaker_meta: {},
      },
      {
        voice_binding_id: "binding-seg-1",
        scope: "segment",
        voice_id: "voice-a",
        model_key: "voice-a",
        gpt_path: "a.ckpt",
        sovits_path: "a.pth",
        speaker_meta: {},
      },
    ]),
    edges: ref([
      {
        edge_id: "edge-1",
        document_id: "doc-1",
        left_segment_id: "seg-1",
        right_segment_id: "seg-2",
        pause_duration_seconds: 0.35,
        boundary_strategy: "crossfade",
        boundary_strategy_locked: false,
        effective_boundary_strategy: "crossfade",
        pause_sample_count: 20,
        boundary_sample_count: 4,
        edge_status: "ready",
        edge_version: 1,
      },
    ]),
    refreshSnapshot: vi.fn(),
    refreshTimeline: vi.fn(),
    refreshFormalSessionState: vi.fn(),
    refreshSessionResources: vi.fn(),
  },
  runtimeStateMock: {
    canMutate: ref(true),
    trackJob: vi.fn(),
    waitForJobTerminal: vi.fn(),
  },
  processingMock: {
    startEdgeUpdate: vi.fn(),
    acceptJob: vi.fn(),
    fail: vi.fn(),
    isInteractionLocked: ref(false),
  },
  apiMock: {
    commitSessionRenderProfile: vi.fn(),
    commitSegmentRenderProfile: vi.fn(),
    commitSegmentRenderProfileBatch: vi.fn(),
    commitSessionVoiceBinding: vi.fn(),
    commitSegmentVoiceBinding: vi.fn(),
    commitSegmentVoiceBindingBatch: vi.fn(),
    commitEdgeConfig: vi.fn(),
    updateEdge: vi.fn(),
  },
  elementPlusMock: {
    warning: vi.fn(),
  },
    };
  })(),
}));

function createVoices() {
  return [
    {
      name: "voice-default",
      gpt_path: "default.ckpt",
      sovits_path: "default.pth",
      ref_audio: "default-preset.wav",
      ref_text: "默认预设",
      ref_lang: "zh",
      description: "默认音色",
      defaults: {
        speed: 1,
        top_k: 15,
        top_p: 1,
        temperature: 1,
        pause_length: 0.3,
      },
      managed: true,
    },
    {
      name: "voice-a",
      gpt_path: "a.ckpt",
      sovits_path: "a.pth",
      ref_audio: "voice-a-preset.wav",
      ref_text: "音色A预设",
      ref_lang: "en",
      description: "音色 A",
      defaults: {
        speed: 1.1,
        top_k: 20,
        top_p: 0.8,
        temperature: 0.9,
        pause_length: 0.35,
      },
      managed: true,
    },
    {
      name: "voice-b",
      gpt_path: "b.ckpt",
      sovits_path: "b.pth",
      ref_audio: "voice-b-preset.wav",
      ref_text: "音色B预设",
      ref_lang: "ja",
      description: "音色 B",
      defaults: {
        speed: 1.2,
        top_k: 25,
        top_p: 0.7,
        temperature: 1,
        pause_length: 0.4,
      },
      managed: true,
    },
  ];
}

vi.mock("@/composables/useEditSession", () => ({
  useEditSession: () => editSessionMock,
}));

vi.mock("@/composables/useRuntimeState", () => ({
  useRuntimeState: () => runtimeStateMock,
}));

vi.mock("@/composables/useWorkspaceProcessing", () => ({
  useWorkspaceProcessing: () => processingMock,
}));

vi.mock("@/api/editSession", () => apiMock);
vi.mock("element-plus", () => ({
  ElMessage: elementPlusMock,
}));

describe("useParameterPanel", () => {
  beforeEach(async () => {
    vi.resetModules();
    vi.clearAllMocks();
    runtimeStateMock.canMutate.value = true;
    runtimeStateMock.waitForJobTerminal.mockResolvedValue("completed");
    processingMock.startEdgeUpdate.mockResolvedValue(undefined);
    apiMock.commitEdgeConfig.mockResolvedValue({
      document_id: "doc-1",
      document_version: 2,
      head_snapshot_id: "snapshot-2",
    });
    apiMock.updateEdge.mockResolvedValue({
      job_id: "job-edge-1",
      document_id: "doc-1",
      status: "queued",
      progress: 0,
      message: "queued",
      updated_at: "2026-04-08T00:00:00Z",
    });
    editSessionMock.sessionStatus.value = "ready";
    editSessionMock.formalStateStatus.value = "ready";
    editSessionMock.snapshot.value = {
      session_status: "ready",
      document_id: "doc-1",
      document_version: 1,
      total_segment_count: 2,
      active_job: null,
      segments: [],
      default_render_profile_id: "profile-session",
      default_voice_binding_id: "binding-session",
    };
    editSessionMock.segments.value = [
      {
        segment_id: "seg-1",
        document_id: "doc-1",
        order_key: 1,
        previous_segment_id: null,
        next_segment_id: "seg-2",
        segment_kind: "speech",
        raw_text: "第一句。",
        normalized_text: "第一句。",
        text_language: "zh",
        render_version: 1,
        render_asset_id: "render-seg-1",
        group_id: null,
        render_profile_id: "profile-seg-1",
        voice_binding_id: "binding-seg-1",
        render_status: "ready",
        segment_revision: 1,
        effective_duration_samples: 50,
        inference_override: {},
        risk_flags: [],
        assembled_audio_span: [0, 50],
      },
      {
        segment_id: "seg-2",
        document_id: "doc-1",
        order_key: 2,
        previous_segment_id: "seg-1",
        next_segment_id: null,
        segment_kind: "speech",
        raw_text: "第二句。",
        normalized_text: "第二句。",
        text_language: "zh",
        render_version: 1,
        render_asset_id: "render-seg-2",
        group_id: null,
        render_profile_id: "profile-seg-2",
        voice_binding_id: "binding-seg-2",
        render_status: "ready",
        segment_revision: 1,
        effective_duration_samples: 50,
        inference_override: {},
        risk_flags: [],
        assembled_audio_span: [50, 100],
      },
    ];
    editSessionMock.groups.value = [];
    editSessionMock.timeline.value = {
      timeline_manifest_id: "timeline-1",
      document_id: "doc-1",
      document_version: 1,
      timeline_version: 1,
      sample_rate: 24000,
      playable_sample_span: [0, 100],
      block_entries: [],
      segment_entries: [
        {
          segment_id: "seg-1",
          order_key: 1,
          start_sample: 0,
          end_sample: 50,
          render_status: "ready",
          group_id: null,
          render_profile_id: "profile-seg-1",
          voice_binding_id: "binding-seg-1",
        },
        {
          segment_id: "seg-2",
          order_key: 2,
          start_sample: 50,
          end_sample: 100,
          render_status: "ready",
          group_id: null,
          render_profile_id: "profile-seg-2",
          voice_binding_id: "binding-seg-2",
        },
      ],
      edge_entries: [],
      markers: [],
    };
    editSessionMock.renderProfiles.value = [
      {
        render_profile_id: "profile-session",
        scope: "session",
        name: "session",
        speed: 1,
        top_k: 15,
        top_p: 1,
        temperature: 1,
        noise_scale: 0.35,
        reference_overrides_by_binding: {},
        reference_audio_path: null,
        reference_text: null,
        reference_language: null,
        extra_overrides: {},
      },
      {
        render_profile_id: "profile-seg-1",
        scope: "segment",
        name: "segment",
        speed: 1.2,
        top_k: 20,
        top_p: 0.8,
        temperature: 0.9,
        noise_scale: 0.4,
        reference_overrides_by_binding: {
          "voice-a:voice-a": {
            reference_audio_path: "seg.wav",
            reference_text: "单段自定义",
            reference_language: "en",
          },
        },
        reference_audio_path: null,
        reference_text: null,
        reference_language: null,
        extra_overrides: {},
      },
      {
        render_profile_id: "profile-seg-2",
        scope: "segment",
        name: "segment-2",
        speed: 1.3,
        top_k: 18,
        top_p: 0.75,
        temperature: 1.05,
        noise_scale: 0.42,
        reference_overrides_by_binding: {},
        reference_audio_path: null,
        reference_text: null,
        reference_language: null,
        extra_overrides: {},
      },
    ];
    editSessionMock.voiceBindings.value = [
      {
        voice_binding_id: "binding-session",
        scope: "session",
        voice_id: "voice-default",
        model_key: "voice-default",
        gpt_path: "default.ckpt",
        sovits_path: "default.pth",
        speaker_meta: {},
      },
      {
        voice_binding_id: "binding-seg-1",
        scope: "segment",
        voice_id: "voice-a",
        model_key: "voice-a",
        gpt_path: "a.ckpt",
        sovits_path: "a.pth",
        speaker_meta: {},
      },
      {
        voice_binding_id: "binding-seg-2",
        scope: "segment",
        voice_id: "voice-b",
        model_key: "voice-b",
        gpt_path: "b.ckpt",
        sovits_path: "b.pth",
        speaker_meta: {},
      },
    ];
    editSessionMock.edges.value = [
      {
        edge_id: "edge-1",
        document_id: "doc-1",
        left_segment_id: "seg-1",
        right_segment_id: "seg-2",
        pause_duration_seconds: 0.35,
        boundary_strategy: "crossfade",
        boundary_strategy_locked: false,
        effective_boundary_strategy: "crossfade",
        pause_sample_count: 20,
        boundary_sample_count: 4,
        edge_status: "ready",
        edge_version: 1,
      },
    ];
    editSessionMock.refreshFormalSessionState.mockResolvedValue({
      snapshot: editSessionMock.snapshot.value,
      timeline: editSessionMock.timeline.value,
      edges: editSessionMock.edges.value,
    });
    const { useSegmentSelection } = await import("../src/composables/useSegmentSelection");
    const { useWorkspaceLightEdit } = await import("../src/composables/useWorkspaceLightEdit");
    useSegmentSelection().clearSelection();
    useWorkspaceLightEdit().clearAll();
    await nextTick();
  });

  it("默认根据空选择进入会话态，并能跟随段选择切到段态", async () => {
    const { useParameterPanel } = await import("../src/composables/useParameterPanel");
    const { useSegmentSelection } = await import("../src/composables/useSegmentSelection");
    const panel = useParameterPanel();
    const selection = useSegmentSelection();

    expect(panel.scopeContext.value.scope).toBe("session");
    expect(panel.resolvedValues.value.voiceBinding.voice_id).toBe("voice-default");

    selection.select("seg-1");
    await nextTick();

    expect(panel.scopeContext.value.scope).toBe("segment");
    expect(panel.scopeContext.value.segmentIds).toEqual(["seg-1"]);
    expect(panel.resolvedValues.value.voiceBinding.voice_id).toBe("voice-a");
  });

  it("更新字段后会记录脏字段，并在 discardDraft 时清空", async () => {
    const { useParameterPanel } = await import("../src/composables/useParameterPanel");
    const panel = useParameterPanel();

    panel.updateRenderProfileField("speed", 1.15);
    panel.updateVoiceBindingField("voice_id", "voice-b");
    await nextTick();

    expect(panel.hasDirty.value).toBe(true);
    expect(Array.from(panel.dirtyFields.value)).toEqual([
      "renderProfile.speed",
      "voiceBinding.voice_id",
    ]);

    panel.discardDraft();
    await nextTick();

    expect(panel.hasDirty.value).toBe(false);
    expect(Array.from(panel.dirtyFields.value)).toEqual([]);
  });

  it("草稿字段会覆盖当前展示值，直到放弃草稿", async () => {
    const { useParameterPanel } = await import("../src/composables/useParameterPanel");
    const panel = useParameterPanel();

    expect(panel.displayValues.value.renderProfile.speed).toBe(1);

    panel.updateRenderProfileField("speed", 1.25);
    await nextTick();

    expect(panel.displayValues.value.renderProfile.speed).toBe(1.25);

    panel.discardDraft();
    await nextTick();

    expect(panel.displayValues.value.renderProfile.speed).toBe(1);
  });

  it("切换音色时会立即切换到目标 binding 的 reference，并在切回时恢复原 override", async () => {
    const { useParameterPanel } = await import("../src/composables/useParameterPanel");
    const { useSegmentSelection } = await import("../src/composables/useSegmentSelection");
    const panel = useParameterPanel();
    const selection = useSegmentSelection();

    (panel as any).setVoices(createVoices());
    selection.select("seg-1");
    await nextTick();

    expect((panel.displayValues.value as any).reference.source).toBe("custom");
    expect((panel.displayValues.value as any).reference.reference_text).toBe("单段自定义");

    panel.updateVoiceBindingField("voice_id", "voice-b");
    panel.updateVoiceBindingField("model_key", "voice-b");
    panel.updateVoiceBindingField("gpt_path", "b.ckpt");
    panel.updateVoiceBindingField("sovits_path", "b.pth");
    await nextTick();

    expect((panel.displayValues.value as any).reference.source).toBe("preset");
    expect((panel.displayValues.value as any).reference.reference_audio_path).toBe("voice-b-preset.wav");
    expect((panel.displayValues.value as any).reference.reference_text).toBe("音色B预设");

    panel.updateVoiceBindingField("voice_id", "voice-a");
    panel.updateVoiceBindingField("model_key", "voice-a");
    panel.updateVoiceBindingField("gpt_path", "a.ckpt");
    panel.updateVoiceBindingField("sovits_path", "a.pth");
    await nextTick();

    expect((panel.displayValues.value as any).reference.source).toBe("custom");
    expect((panel.displayValues.value as any).reference.reference_audio_path).toBe("seg.wav");
    expect((panel.displayValues.value as any).reference.reference_text).toBe("单段自定义");
  });

  it("切回模型预设时会按当前 binding 提交 clear reference_override", async () => {
    const { useParameterPanel } = await import("../src/composables/useParameterPanel");
    const { useSegmentSelection } = await import("../src/composables/useSegmentSelection");
    const panel = useParameterPanel();
    const selection = useSegmentSelection();

    (panel as any).setVoices(createVoices());
    selection.select("seg-1");
    await nextTick();

    (panel as any).updateReferenceSource("preset");
    await panel.submitDraft();

    expect(apiMock.commitSegmentRenderProfile).toHaveBeenCalledWith("seg-1", {
      reference_override: {
        binding_key: "voice-a:voice-a",
        operation: "clear",
      },
    });
  });

  it("同次切音色并写自定义参考时，会用新 binding key 提交 upsert", async () => {
    const { useParameterPanel } = await import("../src/composables/useParameterPanel");
    const panel = useParameterPanel();

    (panel as any).setVoices(createVoices());

    panel.updateVoiceBindingField("voice_id", "voice-b");
    panel.updateVoiceBindingField("model_key", "voice-b");
    panel.updateVoiceBindingField("gpt_path", "b.ckpt");
    panel.updateVoiceBindingField("sovits_path", "b.pth");
    (panel as any).updateReferenceSource("custom");
    (panel as any).updateReferenceField("reference_audio_path", "voice-b-custom.wav");
    (panel as any).updateReferenceField("reference_text", "音色B自定义");
    (panel as any).updateReferenceField("reference_language", "ja");
    await panel.submitDraft();

    expect(apiMock.commitSessionVoiceBinding).toHaveBeenCalledWith({
      voice_id: "voice-b",
      model_key: "voice-b",
      gpt_path: "b.ckpt",
      sovits_path: "b.pth",
    });
    expect(apiMock.commitSessionRenderProfile).toHaveBeenCalledWith({
      reference_override: {
        binding_key: "voice-b:voice-b",
        operation: "upsert",
        reference_audio_path: "voice-b-custom.wav",
        reference_text: "音色B自定义",
        reference_language: "ja",
      },
    });
  });

  it("批量态统一切到某个音色后，reference 预览仍按整批真实结果保留 mixed", async () => {
    const { useParameterPanel } = await import("../src/composables/useParameterPanel");
    const { useSegmentSelection } = await import("../src/composables/useSegmentSelection");
    const panel = useParameterPanel();
    const selection = useSegmentSelection();

    editSessionMock.renderProfiles.value = [
      editSessionMock.renderProfiles.value[0],
      {
        ...editSessionMock.renderProfiles.value[1],
        reference_overrides_by_binding: {
          ...editSessionMock.renderProfiles.value[1].reference_overrides_by_binding,
          "voice-b:voice-b": {
            reference_audio_path: "seg-b.wav",
            reference_text: "段一切到B后的自定义",
            reference_language: "ja",
          },
        },
      },
      editSessionMock.renderProfiles.value[2],
    ];

    (panel as any).setVoices(createVoices());
    selection.select("seg-1");
    selection.toggleSelect("seg-2");
    await nextTick();

    expect(panel.scopeContext.value.scope).toBe("batch");
    expect((panel.displayValues.value as any).reference.source).toBe("__MIXED__");

    panel.updateVoiceBindingField("voice_id", "voice-b");
    panel.updateVoiceBindingField("model_key", "voice-b");
    panel.updateVoiceBindingField("gpt_path", "b.ckpt");
    panel.updateVoiceBindingField("sovits_path", "b.pth");
    await nextTick();

    expect((panel.displayValues.value as any).reference.source).toBe("__MIXED__");
    expect((panel.displayValues.value as any).reference.reference_audio_path).toBe("__MIXED__");
    expect((panel.displayValues.value as any).reference.reference_text).toBe("__MIXED__");
  });

  it("同一 scope 刷新中会保留最后一次稳定参数，并标记为 resolving", async () => {
    const { useParameterPanel } = await import("../src/composables/useParameterPanel");
    const panel = useParameterPanel();

    expect(panel.displayValues.value.renderProfile.speed).toBe(1);

    editSessionMock.formalStateStatus.value = "refreshing";
    editSessionMock.snapshot.value = {
      ...editSessionMock.snapshot.value,
      document_version: 2,
      default_render_profile_id: "profile-session-2",
      default_voice_binding_id: "binding-session-2",
    };
    editSessionMock.renderProfiles.value = [];
    editSessionMock.voiceBindings.value = [];
    await nextTick();

    expect((panel as any).resolvedStatus.value).toBe("resolving");
    expect(panel.displayValues.value.renderProfile.speed).toBe(1);
    expect(panel.displayValues.value.voiceBinding.voice_id).toBe("voice-default");
  });

  it("scope 切换且正式态仍在刷新时，不会复用旧 scope 的稳定参数", async () => {
    const { useParameterPanel } = await import("../src/composables/useParameterPanel");
    const { useSegmentSelection } = await import("../src/composables/useSegmentSelection");
    const panel = useParameterPanel();
    const selection = useSegmentSelection();

    selection.select("seg-1");
    await nextTick();

    expect(panel.scopeContext.value.scope).toBe("segment");
    expect(panel.displayValues.value.voiceBinding.voice_id).toBe("voice-a");

    editSessionMock.formalStateStatus.value = "refreshing";
    editSessionMock.renderProfiles.value = [];
    editSessionMock.voiceBindings.value = [];
    selection.clearSelection();
    await nextTick();

    expect(panel.scopeContext.value.scope).toBe("session");
    expect((panel as any).resolvedStatus.value).toBe("resolving");
    expect(panel.displayValues.value.renderProfile.speed).toBeNull();
    expect(panel.displayValues.value.voiceBinding.voice_id).toBeNull();
  });

  it("正式态 ready 但引用不可解析时，会显式标记 unresolved 而不是伪装成默认值", async () => {
    const { useParameterPanel } = await import("../src/composables/useParameterPanel");
    const panel = useParameterPanel();

    editSessionMock.formalStateStatus.value = "ready";
    editSessionMock.snapshot.value = {
      ...editSessionMock.snapshot.value,
      default_render_profile_id: "missing-profile",
      default_voice_binding_id: "missing-binding",
    };
    editSessionMock.renderProfiles.value = [];
    editSessionMock.voiceBindings.value = [];
    await nextTick();

    expect((panel as any).resolvedStatus.value).toBe("unresolved");
    expect(panel.displayValues.value.renderProfile.speed).toBeNull();
    expect(panel.displayValues.value.voiceBinding.voice_id).toBeNull();
  });

  it("安全 edge 提交会走异步更新作业，并把正式刷新交给 workspace processing", async () => {
    const { useParameterPanel } = await import("../src/composables/useParameterPanel");
    const { useSegmentSelection } = await import("../src/composables/useSegmentSelection");
    const panel = useParameterPanel();
    const selection = useSegmentSelection();

    selection.selectEdge("edge-1");
    await nextTick();

    panel.updateEdgeField("pause_duration_seconds", 0.47);
    await panel.submitDraft();

    expect(apiMock.updateEdge).toHaveBeenCalledWith("edge-1", {
      pause_duration_seconds: 0.47,
    });
    expect(apiMock.commitEdgeConfig).not.toHaveBeenCalled();
    expect(processingMock.startEdgeUpdate).toHaveBeenCalledWith({
      summary: "停顿 0.35 -> 0.47",
    });
    expect(processingMock.acceptJob).toHaveBeenCalledWith({
      job: expect.objectContaining({ job_id: "job-edge-1" }),
      jobKind: "edge-compose",
    });
    expect(runtimeStateMock.trackJob).toHaveBeenCalledWith(
      expect.objectContaining({ job_id: "job-edge-1" }),
      {
        initialRendering: false,
        refreshSessionOnTerminal: false,
      },
    );
    expect(runtimeStateMock.waitForJobTerminal).not.toHaveBeenCalled();
    expect(editSessionMock.refreshSnapshot).not.toHaveBeenCalled();
    expect(editSessionMock.refreshTimeline).not.toHaveBeenCalled();
    expect(panel.hasDirty.value).toBe(false);
  });

  it("非 edge 参数提交后会直接刷新 formal session state，而不是分步刷新 snapshot/timeline", async () => {
    const { useParameterPanel } = await import("../src/composables/useParameterPanel");
    const panel = useParameterPanel();

    panel.updateRenderProfileField("speed", 1.15);
    await panel.submitDraft();

    expect(apiMock.commitSessionRenderProfile).toHaveBeenCalledWith({
      speed: 1.15,
    });
    expect(editSessionMock.refreshFormalSessionState).toHaveBeenCalledTimes(1);
    expect(editSessionMock.refreshSnapshot).not.toHaveBeenCalled();
    expect(editSessionMock.refreshTimeline).not.toHaveBeenCalled();
  });

  it("影响脏段的 edge 提交会被拦截，并提示先重推理", async () => {
    const { useParameterPanel } = await import("../src/composables/useParameterPanel");
    const { useSegmentSelection } = await import("../src/composables/useSegmentSelection");
    const { useWorkspaceLightEdit } = await import("../src/composables/useWorkspaceLightEdit");
    const panel = useParameterPanel();
    const selection = useSegmentSelection();
    const lightEdit = useWorkspaceLightEdit();

    lightEdit.replaceAllDrafts({
      "seg-2": "第二句（未重推理）",
    });
    selection.selectEdge("edge-1");
    await nextTick();

    panel.updateEdgeField("pause_duration_seconds", 0.47);

    await expect(panel.submitDraft()).rejects.toThrow(
      "该停顿会影响待重推理段，请先重推理",
    );

    expect(elementPlusMock.warning).toHaveBeenCalledWith(
      "该停顿会影响待重推理段，请先重推理",
    );
    expect(apiMock.commitEdgeConfig).not.toHaveBeenCalled();
    expect(apiMock.updateEdge).not.toHaveBeenCalled();
    expect(editSessionMock.refreshSnapshot).not.toHaveBeenCalled();
    expect(editSessionMock.refreshTimeline).not.toHaveBeenCalled();
    expect(panel.hasDirty.value).toBe(true);
  });

  it("edge 草稿会暴露 dirtyEdgeIds，并在恢复原值后清空", async () => {
    const { useParameterPanel } = await import("../src/composables/useParameterPanel");
    const { useSegmentSelection } = await import("../src/composables/useSegmentSelection");
    const panel = useParameterPanel();
    const selection = useSegmentSelection();

    selection.selectEdge("edge-1");
    await nextTick();

    expect(Array.from(panel.dirtyEdgeIds.value)).toEqual([]);

    panel.updateEdgeField("pause_duration_seconds", 0.47);
    await nextTick();

    expect(Array.from(panel.dirtyEdgeIds.value)).toEqual(["edge-1"]);

    panel.updateEdgeField("pause_duration_seconds", 0.35);
    await nextTick();

    expect(Array.from(panel.dirtyEdgeIds.value)).toEqual([]);

    panel.updateEdgeField("boundary_strategy", "hold");
    await nextTick();

    expect(Array.from(panel.dirtyEdgeIds.value)).toEqual(["edge-1"]);
  });

  it("锁定边界策略的 edge 会忽略策略修改，只保留停顿可调", async () => {
    const { useParameterPanel } = await import("../src/composables/useParameterPanel");
    const { useSegmentSelection } = await import("../src/composables/useSegmentSelection");
    const panel = useParameterPanel();
    const selection = useSegmentSelection();

    editSessionMock.edges.value = [
      {
        ...editSessionMock.edges.value[0],
        boundary_strategy: "crossfade_only",
        boundary_strategy_locked: true,
        effective_boundary_strategy: "crossfade_only",
      },
    ];

    selection.selectEdge("edge-1");
    await nextTick();

    panel.updateEdgeField("boundary_strategy", "hard_cut");
    panel.updateEdgeField("pause_duration_seconds", 0.42);
    await nextTick();

    expect(Array.from(panel.dirtyFields.value)).toEqual([
      "edge.pause_duration_seconds",
    ]);
    expect(panel.displayValues.value.edge?.boundary_strategy).toBe("crossfade_only");
    expect(panel.displayValues.value.edge?.boundary_strategy_locked).toBe(true);
  });
});
