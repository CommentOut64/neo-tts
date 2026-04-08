import type {
  EditSessionSnapshot,
  EditableSegment,
  EditableEdge,
  RenderProfile,
  SegmentGroup,
  TimelineManifest,
  VoiceBinding,
} from "@/types/editSession";

import type { ParameterPanelScopeContext } from "./resolveParameterScope";

export const MIXED_VALUE = "__MIXED__" as const;

type MixedValue = typeof MIXED_VALUE;
type MaybeMixed<T> = T | MixedValue | null;

export interface ResolvedParameterPanelValues {
  renderProfile: {
    speed: MaybeMixed<number>;
    top_k: MaybeMixed<number>;
    top_p: MaybeMixed<number>;
    temperature: MaybeMixed<number>;
    noise_scale: MaybeMixed<number>;
    reference_audio_path: MaybeMixed<string>;
    reference_text: MaybeMixed<string>;
    reference_language: MaybeMixed<string>;
  };
  voiceBinding: {
    voice_id: MaybeMixed<string>;
    model_key: MaybeMixed<string>;
    gpt_path: MaybeMixed<string>;
    sovits_path: MaybeMixed<string>;
  };
  edge: {
    pause_duration_seconds: number;
    boundary_strategy: string;
    effective_boundary_strategy: string | null;
  } | null;
}

function pickMixed<T>(values: T[]): T | MixedValue | null {
  if (values.length === 0) return null;
  const first = values[0];
  return values.every((value) => value === first) ? first : MIXED_VALUE;
}

function buildEmptyResolvedValues(): ResolvedParameterPanelValues {
  return {
    renderProfile: {
      speed: null,
      top_k: null,
      top_p: null,
      temperature: null,
      noise_scale: null,
      reference_audio_path: null,
      reference_text: null,
      reference_language: null,
    },
    voiceBinding: {
      voice_id: null,
      model_key: null,
      gpt_path: null,
      sovits_path: null,
    },
    edge: null,
  };
}

export function resolveEffectiveParameters(input: {
  scope: ParameterPanelScopeContext["scope"];
  segmentIds: string[];
  edgeId: string | null;
  snapshot: EditSessionSnapshot | null;
  segments: EditableSegment[];
  groups: SegmentGroup[];
  timeline: TimelineManifest | null;
  renderProfiles: RenderProfile[];
  voiceBindings: VoiceBinding[];
  edges: EditableEdge[];
}): ResolvedParameterPanelValues {
  const result = buildEmptyResolvedValues();
  const profileById = new Map(
    input.renderProfiles.map((profile) => [profile.render_profile_id, profile] as const),
  );
  const groupById = new Map(
    input.groups.map((group) => [group.group_id, group] as const),
  );
  const bindingById = new Map(
    input.voiceBindings.map((binding) => [binding.voice_binding_id, binding] as const),
  );

  if (input.scope === "edge") {
    const edge = input.edges.find((item) => item.edge_id === input.edgeId);
    if (!edge) return result;
    return {
      ...result,
      edge: {
        pause_duration_seconds: edge.pause_duration_seconds,
        boundary_strategy: edge.boundary_strategy,
        effective_boundary_strategy: edge.effective_boundary_strategy,
      },
    };
  }

  if (input.scope === "session") {
    const profile = input.snapshot?.default_render_profile_id
      ? profileById.get(input.snapshot.default_render_profile_id)
      : null;
    const binding = input.snapshot?.default_voice_binding_id
      ? bindingById.get(input.snapshot.default_voice_binding_id)
      : null;

    return {
      ...result,
      renderProfile: {
        speed: profile?.speed ?? null,
        top_k: profile?.top_k ?? null,
        top_p: profile?.top_p ?? null,
        temperature: profile?.temperature ?? null,
        noise_scale: profile?.noise_scale ?? null,
        reference_audio_path: profile?.reference_audio_path ?? null,
        reference_text: profile?.reference_text ?? null,
        reference_language: profile?.reference_language ?? null,
      },
      voiceBinding: {
        voice_id: binding?.voice_id ?? null,
        model_key: binding?.model_key ?? null,
        gpt_path: binding?.gpt_path ?? null,
        sovits_path: binding?.sovits_path ?? null,
      },
    };
  }

  const selectedSegments = input.segments.filter((segment) => input.segmentIds.includes(segment.segment_id));

  const resolveProfileForSegment = (segment: EditableSegment): RenderProfile | null => {
    let profileId = input.snapshot?.default_render_profile_id ?? null;
    if (segment.group_id) {
      profileId = groupById.get(segment.group_id)?.render_profile_id ?? profileId;
    }
    profileId = segment.render_profile_id ?? profileId;
    return profileId ? profileById.get(profileId) ?? null : null;
  };

  const resolveBindingForSegment = (segment: EditableSegment): VoiceBinding | null => {
    let bindingId = input.snapshot?.default_voice_binding_id ?? null;
    if (segment.group_id) {
      bindingId = groupById.get(segment.group_id)?.voice_binding_id ?? bindingId;
    }
    bindingId = segment.voice_binding_id ?? bindingId;
    return bindingId ? bindingById.get(bindingId) ?? null : null;
  };

  const profiles = (selectedSegments.length > 0
    ? selectedSegments.map(resolveProfileForSegment)
    : input.timeline?.segment_entries
        .filter((entry) => input.segmentIds.includes(entry.segment_id))
        .map((entry) => (entry.render_profile_id ? profileById.get(entry.render_profile_id) ?? null : null)) ?? []
  ).filter((profile): profile is RenderProfile => profile !== null);
  const bindings = (selectedSegments.length > 0
    ? selectedSegments.map(resolveBindingForSegment)
    : input.timeline?.segment_entries
        .filter((entry) => input.segmentIds.includes(entry.segment_id))
        .map((entry) => (entry.voice_binding_id ? bindingById.get(entry.voice_binding_id) ?? null : null)) ?? []
  ).filter((binding): binding is VoiceBinding => binding !== null);

  return {
    ...result,
    renderProfile: {
      speed: pickMixed(profiles.map((profile) => profile.speed)),
      top_k: pickMixed(profiles.map((profile) => profile.top_k)),
      top_p: pickMixed(profiles.map((profile) => profile.top_p)),
      temperature: pickMixed(profiles.map((profile) => profile.temperature)),
      noise_scale: pickMixed(profiles.map((profile) => profile.noise_scale)),
      reference_audio_path: pickMixed(profiles.map((profile) => profile.reference_audio_path)),
      reference_text: pickMixed(profiles.map((profile) => profile.reference_text)),
      reference_language: pickMixed(profiles.map((profile) => profile.reference_language)),
    },
    voiceBinding: {
      voice_id: pickMixed(bindings.map((binding) => binding.voice_id)),
      model_key: pickMixed(bindings.map((binding) => binding.model_key)),
      gpt_path: pickMixed(bindings.map((binding) => binding.gpt_path)),
      sovits_path: pickMixed(bindings.map((binding) => binding.sovits_path)),
    },
  };
}
