import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick, ref } from "vue";

vi.mock("@/composables/useEditSession", () => ({
  useEditSession: () => ({
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
        reference_audio_path: "default.wav",
        reference_text: "默认",
        reference_language: "zh",
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
        reference_audio_path: "seg.wav",
        reference_text: "单段",
        reference_language: "en",
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
        effective_boundary_strategy: "crossfade",
        pause_sample_count: 20,
        boundary_sample_count: 4,
        edge_status: "ready",
        edge_version: 1,
      },
    ]),
    refreshSnapshot: vi.fn(),
    refreshTimeline: vi.fn(),
    refreshSessionResources: vi.fn(),
  }),
}));

describe("useParameterPanel", () => {
  beforeEach(async () => {
    vi.resetModules();
    const { useSegmentSelection } = await import("../src/composables/useSegmentSelection");
    useSegmentSelection().clearSelection();
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
});
