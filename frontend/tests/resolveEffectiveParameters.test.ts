import { describe, expect, it } from "vitest";

import { buildReferenceBindingKey } from "../src/features/reference-binding";
import {
  MIXED_VALUE,
  resolveEffectiveParameters,
} from "../src/components/workspace/parameter-panel/resolveEffectiveParameters";
import type {
  EditSessionSnapshot,
  EditableSegment,
  EditableEdge,
  RenderProfile,
  SegmentGroup,
  TimelineManifest,
  VoiceBinding,
} from "../src/types/editSession";
import type { VoiceProfile } from "../src/types/tts";

function createSnapshot(): EditSessionSnapshot {
  return {
    session_status: "ready",
    document_id: "doc-1",
    document_version: 3,
    total_segment_count: 2,
    active_job: null,
    segments: [],
    default_render_profile_id: "profile-session",
    default_voice_binding_id: "binding-session",
  };
}

function createVoices(): VoiceProfile[] {
  return [
    {
      name: "voice-default",
      gpt_path: "models/default.ckpt",
      sovits_path: "models/default.pth",
      ref_audio: "voices/default-preset.wav",
      ref_text: "默认音色预设文本",
      ref_lang: "zh",
      description: "默认音色",
      defaults: {
        speed: 1,
        temperature: 1,
        top_p: 1,
        top_k: 15,
        pause_length: 0.3,
      },
      managed: true,
    },
    {
      name: "voice-a",
      gpt_path: "models/a.ckpt",
      sovits_path: "models/a.pth",
      ref_audio: "voices/a-preset.wav",
      ref_text: "音色A预设文本",
      ref_lang: "en",
      description: "音色 A",
      defaults: {
        speed: 1.1,
        temperature: 0.9,
        top_p: 0.8,
        top_k: 20,
        pause_length: 0.35,
      },
      managed: true,
    },
    {
      name: "voice-b",
      gpt_path: "models/b.ckpt",
      sovits_path: "models/b.pth",
      ref_audio: "voices/b-preset.wav",
      ref_text: "音色B预设文本",
      ref_lang: "ja",
      description: "音色 B",
      defaults: {
        speed: 1.2,
        temperature: 1,
        top_p: 0.7,
        top_k: 25,
        pause_length: 0.4,
      },
      managed: true,
    },
  ];
}

function createProfiles(): RenderProfile[] {
  return [
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
      name: "segment-1",
      speed: 1.1,
      top_k: 20,
      top_p: 0.8,
      temperature: 0.9,
      noise_scale: 0.4,
      reference_overrides_by_binding: {
        [buildReferenceBindingKey({
          voiceId: "voice-a",
          modelKey: "voice-a",
        })]: {
          reference_audio_path: "voices/custom-a.wav",
          reference_text: "音色A自定义文本",
          reference_language: null,
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
      top_k: 25,
      top_p: 0.7,
      temperature: 1.2,
      noise_scale: 0.5,
      reference_overrides_by_binding: {},
      reference_audio_path: null,
      reference_text: null,
      reference_language: null,
      extra_overrides: {},
    },
  ];
}

function createBindings(): VoiceBinding[] {
  return [
    {
      voice_binding_id: "binding-session",
      scope: "session",
      voice_id: "voice-default",
      model_key: "voice-default",
      gpt_path: "models/default.ckpt",
      sovits_path: "models/default.pth",
      speaker_meta: {},
    },
    {
      voice_binding_id: "binding-seg-1",
      scope: "segment",
      voice_id: "voice-a",
      model_key: "voice-a",
      gpt_path: "models/a.ckpt",
      sovits_path: "models/a.pth",
      speaker_meta: {},
    },
    {
      voice_binding_id: "binding-seg-2",
      scope: "segment",
      voice_id: "voice-b",
      model_key: "voice-b",
      gpt_path: "models/b.ckpt",
      sovits_path: "models/b.pth",
      speaker_meta: {},
    },
  ];
}

function createSegments(): EditableSegment[] {
  return [
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
      effective_duration_samples: 40,
      inference_override: {},
      risk_flags: [],
      assembled_audio_span: [0, 40],
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
      effective_duration_samples: 60,
      inference_override: {},
      risk_flags: [],
      assembled_audio_span: [40, 100],
    },
  ];
}

function createInheritedSegments(): EditableSegment[] {
  return [
    {
      ...createSegments()[0],
      render_profile_id: null,
      voice_binding_id: null,
    },
  ];
}

function createGroups(): SegmentGroup[] {
  return [];
}

function createTimeline(): TimelineManifest {
  return {
    timeline_manifest_id: "timeline-1",
    document_id: "doc-1",
    document_version: 3,
    timeline_version: 3,
    sample_rate: 24000,
    playable_sample_span: [0, 100],
    block_entries: [],
    segment_entries: [
      {
        segment_id: "seg-1",
        order_key: 1,
        start_sample: 0,
        end_sample: 40,
        render_status: "ready",
        group_id: null,
        render_profile_id: "profile-seg-1",
        voice_binding_id: "binding-seg-1",
      },
      {
        segment_id: "seg-2",
        order_key: 2,
        start_sample: 40,
        end_sample: 100,
        render_status: "ready",
        group_id: null,
        render_profile_id: "profile-seg-2",
        voice_binding_id: "binding-seg-2",
      },
    ],
    edge_entries: [
      {
        edge_id: "edge-1",
        left_segment_id: "seg-1",
        right_segment_id: "seg-2",
        pause_duration_seconds: 0.45,
        boundary_strategy: "crossfade",
        effective_boundary_strategy: "crossfade",
        boundary_start_sample: 38,
        boundary_end_sample: 42,
        pause_start_sample: 42,
        pause_end_sample: 52,
      },
    ],
    markers: [],
  };
}

function createInheritedTimeline(): TimelineManifest {
  return {
    timeline_manifest_id: "timeline-inherited",
    document_id: "doc-1",
    document_version: 3,
    timeline_version: 3,
    sample_rate: 24000,
    playable_sample_span: [0, 100],
    block_entries: [],
    segment_entries: [
      {
        segment_id: "seg-1",
        order_key: 1,
        start_sample: 0,
        end_sample: 40,
        render_status: "ready",
        group_id: null,
        render_profile_id: null,
        voice_binding_id: null,
      },
    ],
    edge_entries: [],
    markers: [],
  };
}

function createEdges(): EditableEdge[] {
  return [
    {
      edge_id: "edge-1",
      document_id: "doc-1",
      left_segment_id: "seg-1",
      right_segment_id: "seg-2",
      pause_duration_seconds: 0.45,
      boundary_strategy: "crossfade",
      boundary_strategy_locked: true,
      effective_boundary_strategy: "crossfade",
      pause_sample_count: 10,
      boundary_sample_count: 4,
      edge_status: "ready",
      edge_version: 1,
    },
  ];
}

describe("resolveEffectiveParameters", () => {
  const snapshot = createSnapshot();
  const voices = createVoices();
  const renderProfiles = createProfiles();
  const voiceBindings = createBindings();
  const groups = createGroups();
  const segments = createSegments();
  const timeline = createTimeline();
  const edges = createEdges();

  it("会话态会基于当前 binding 解析模型预设 reference", () => {
    const resolved = resolveEffectiveParameters({
      scope: "session",
      segmentIds: [],
      edgeId: null,
      snapshot,
      segments,
      groups,
      timeline,
      renderProfiles,
      voiceBindings,
      edges,
      voices,
    } as never);
    const reference = (resolved as any).reference;

    expect(resolved.renderProfile.speed).toBe(1);
    expect(resolved.voiceBinding.voice_id).toBe("voice-default");
    expect(reference.source).toBe("preset");
    expect(reference.binding_key).toBe("voice-default:voice-default");
    expect(reference.reference_audio_path).toBe("voices/default-preset.wav");
    expect(reference.reference_text).toBe("默认音色预设文本");
    expect(reference.reference_language).toBe("zh");
    expect(reference.preset_text).toBe("默认音色预设文本");
  });

  it("单段态会把当前 binding 的 override 与 voice preset 合并", () => {
    const resolved = resolveEffectiveParameters({
      scope: "segment",
      segmentIds: ["seg-1"],
      edgeId: null,
      snapshot,
      segments,
      groups,
      timeline,
      renderProfiles,
      voiceBindings,
      edges,
      voices,
    } as never);
    const reference = (resolved as any).reference;

    expect(resolved.renderProfile.speed).toBe(1.1);
    expect(resolved.voiceBinding.voice_id).toBe("voice-a");
    expect(reference.source).toBe("custom");
    expect(reference.binding_key).toBe("voice-a:voice-a");
    expect(reference.reference_audio_path).toBe("voices/custom-a.wav");
    expect(reference.reference_text).toBe("音色A自定义文本");
    expect(reference.reference_language).toBe("en");
    expect(reference.preset_audio_path).toBe("voices/a-preset.wav");
  });

  it("单段态在没有直接 profile 或 binding 时回退到会话默认 binding 的 preset", () => {
    const resolved = resolveEffectiveParameters({
      scope: "segment",
      segmentIds: ["seg-1"],
      edgeId: null,
      snapshot,
      segments: createInheritedSegments(),
      groups,
      timeline: createInheritedTimeline(),
      renderProfiles,
      voiceBindings,
      edges,
      voices,
    } as never);
    const reference = (resolved as any).reference;

    expect(resolved.renderProfile.speed).toBe(1);
    expect(resolved.voiceBinding.voice_id).toBe("voice-default");
    expect(reference.source).toBe("preset");
    expect(reference.reference_audio_path).toBe("voices/default-preset.wav");
    expect(reference.reference_text).toBe("默认音色预设文本");
  });

  it("批量态会对 reference 的 source、binding 与内容返回 MIXED_VALUE", () => {
    const resolved = resolveEffectiveParameters({
      scope: "batch",
      segmentIds: ["seg-1", "seg-2"],
      edgeId: null,
      snapshot,
      segments,
      groups,
      timeline,
      renderProfiles,
      voiceBindings,
      edges,
      voices,
    } as never);
    const reference = (resolved as any).reference;

    expect(resolved.renderProfile.speed).toBe(MIXED_VALUE);
    expect(resolved.voiceBinding.voice_id).toBe(MIXED_VALUE);
    expect(reference.source).toBe(MIXED_VALUE);
    expect(reference.binding_key).toBe(MIXED_VALUE);
    expect(reference.reference_text).toBe(MIXED_VALUE);
    expect(reference.reference_language).toBe(MIXED_VALUE);
  });

  it("edge 态仍然只返回边参数", () => {
    const resolved = resolveEffectiveParameters({
      scope: "edge",
      segmentIds: [],
      edgeId: "edge-1",
      snapshot,
      segments,
      groups,
      timeline,
      renderProfiles,
      voiceBindings,
      edges,
      voices,
    } as never);

    expect(resolved.edge?.pause_duration_seconds).toBe(0.45);
    expect(resolved.edge?.boundary_strategy).toBe("crossfade");
    expect(resolved.edge?.boundary_strategy_locked).toBe(true);
    expect(resolved.edge?.effective_boundary_strategy).toBe("crossfade");
  });
});
