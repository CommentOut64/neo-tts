import type {
  BindingReference,
  EditSessionSnapshot,
  EditableSegment,
  EditableEdge,
  RenderProfile,
  SegmentGroup,
  TimelineManifest,
  VoiceBinding,
} from "@/types/editSession";
import { resolveBindingReferenceState } from "@/features/reference-binding";
import type { RegistryBindingOption } from "@/types/ttsRegistry";

import type { ParameterPanelScopeContext } from "./resolveParameterScope";

export const MIXED_VALUE = "__MIXED__" as const;

type MixedValue = typeof MIXED_VALUE;
type MaybeMixed<T> = T | MixedValue | null;

export interface ResolvedReferenceState {
  source: MaybeMixed<"preset" | "custom">;
  reference_scope: MaybeMixed<"voice_preset" | "session_override">;
  binding_key: MaybeMixed<string>;
  reference_identity: MaybeMixed<string>;
  session_reference_asset_id: MaybeMixed<string>;
  reference_audio_fingerprint: MaybeMixed<string>;
  reference_audio_path: MaybeMixed<string>;
  reference_text: MaybeMixed<string>;
  reference_text_fingerprint: MaybeMixed<string>;
  reference_language: MaybeMixed<string>;
  preset_audio_path: MaybeMixed<string>;
  preset_text: MaybeMixed<string>;
  preset_language: MaybeMixed<string>;
}

export interface ResolvedParameterPanelValues {
  renderProfile: {
    speed: MaybeMixed<number>;
    top_k: MaybeMixed<number>;
    top_p: MaybeMixed<number>;
    temperature: MaybeMixed<number>;
    noise_scale: MaybeMixed<number>;
  };
  voiceBinding: {
    binding_ref: MaybeMixed<BindingReference>;
    voice_id: MaybeMixed<string>;
    model_key: MaybeMixed<string>;
    gpt_path: MaybeMixed<string>;
    sovits_path: MaybeMixed<string>;
  };
  reference: ResolvedReferenceState;
  edge: {
    pause_duration_seconds: number;
    boundary_strategy: string;
    boundary_strategy_locked: boolean;
    effective_boundary_strategy: string | null;
  } | null;
}

function pickMixed<T>(values: T[]): T | MixedValue | null {
  if (values.length === 0) return null;
  const first = values[0];
  return values.every((value) => value === first) ? first : MIXED_VALUE;
}

function buildEmptyReferenceState(): ResolvedReferenceState {
  return {
    source: null,
    reference_scope: null,
    binding_key: null,
    reference_identity: null,
    session_reference_asset_id: null,
    reference_audio_fingerprint: null,
    reference_audio_path: null,
    reference_text: null,
    reference_text_fingerprint: null,
    reference_language: null,
    preset_audio_path: null,
    preset_text: null,
    preset_language: null,
  };
}

function buildEmptyResolvedValues(): ResolvedParameterPanelValues {
  return {
    renderProfile: {
      speed: null,
      top_k: null,
      top_p: null,
      temperature: null,
      noise_scale: null,
    },
    voiceBinding: {
      binding_ref: null,
      voice_id: null,
      model_key: null,
      gpt_path: null,
      sovits_path: null,
    },
    reference: buildEmptyReferenceState(),
    edge: null,
  };
}

function resolveProfileById(
  profileById: Map<string, RenderProfile>,
  profileId: string | null | undefined,
): RenderProfile | null {
  return profileId ? profileById.get(profileId) ?? null : null;
}

function resolveBindingById(
  bindingById: Map<string, VoiceBinding>,
  bindingId: string | null | undefined,
): VoiceBinding | null {
  return bindingId ? bindingById.get(bindingId) ?? null : null;
}

function toBindingKey(bindingRef: BindingReference | null | undefined): string | null {
  if (!bindingRef) {
    return null;
  }
  return [
    bindingRef.workspace_id,
    bindingRef.main_model_id,
    bindingRef.submodel_id,
    bindingRef.preset_id,
  ].join(":");
}

function pickMixedBindingReference(
  values: Array<BindingReference | null | undefined>,
): BindingReference | MixedValue | null {
  if (values.length === 0) {
    return null;
  }

  const normalized = values.map((value) => value ?? null);
  const firstKey = toBindingKey(normalized[0]);
  const isSame = normalized.every((value) => toBindingKey(value) === firstKey);
  return isSame ? normalized[0] : MIXED_VALUE;
}

function pickReferenceState(
  states: ReturnType<typeof resolveBindingReferenceState>[],
): ResolvedReferenceState {
  return {
    source: pickMixed(states.map((state) => state.source)),
    reference_scope: pickMixed(states.map((state) => state.reference_scope)),
    binding_key: pickMixed(states.map((state) => state.binding_key)),
    reference_identity: pickMixed(states.map((state) => state.reference_identity)),
    session_reference_asset_id: pickMixed(states.map((state) => state.session_reference_asset_id)),
    reference_audio_fingerprint: pickMixed(states.map((state) => state.reference_audio_fingerprint)),
    reference_audio_path: pickMixed(states.map((state) => state.reference_audio_path)),
    reference_text: pickMixed(states.map((state) => state.reference_text)),
    reference_text_fingerprint: pickMixed(states.map((state) => state.reference_text_fingerprint)),
    reference_language: pickMixed(states.map((state) => state.reference_language)),
    preset_audio_path: pickMixed(states.map((state) => state.preset_audio_path)),
    preset_text: pickMixed(states.map((state) => state.preset_text)),
    preset_language: pickMixed(states.map((state) => state.preset_language)),
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
  bindingOptions: RegistryBindingOption[];
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
        boundary_strategy_locked: Boolean(edge.boundary_strategy_locked),
        effective_boundary_strategy: edge.effective_boundary_strategy,
      },
    };
  }

  if (input.scope === "session") {
    const profile = resolveProfileById(
      profileById,
      input.snapshot?.default_render_profile_id,
    );
    const binding = resolveBindingById(
      bindingById,
      input.snapshot?.default_voice_binding_id,
    );

    return {
      ...result,
      renderProfile: {
        speed: profile?.speed ?? null,
        top_k: profile?.top_k ?? null,
        top_p: profile?.top_p ?? null,
        temperature: profile?.temperature ?? null,
        noise_scale: profile?.noise_scale ?? null,
      },
      voiceBinding: {
        binding_ref: binding?.binding_ref ?? null,
        voice_id: binding?.voice_id ?? null,
        model_key: binding?.model_key ?? null,
        gpt_path: binding?.gpt_path ?? null,
        sovits_path: binding?.sovits_path ?? null,
      },
      reference: resolveBindingReferenceState({
        binding,
        profile,
        bindingOptions: input.bindingOptions,
      }),
    };
  }

  const selectedSegments = input.segments.filter((segment) =>
    input.segmentIds.includes(segment.segment_id),
  );

  const resolveProfileForSegment = (segment: EditableSegment): RenderProfile | null => {
    let profileId = input.snapshot?.default_render_profile_id ?? null;
    if (segment.group_id) {
      profileId = groupById.get(segment.group_id)?.render_profile_id ?? profileId;
    }
    profileId = segment.render_profile_id ?? profileId;
    return resolveProfileById(profileById, profileId);
  };

  const resolveBindingForSegment = (segment: EditableSegment): VoiceBinding | null => {
    let bindingId = input.snapshot?.default_voice_binding_id ?? null;
    if (segment.group_id) {
      bindingId = groupById.get(segment.group_id)?.voice_binding_id ?? bindingId;
    }
    bindingId = segment.voice_binding_id ?? bindingId;
    return resolveBindingById(bindingById, bindingId);
  };

  const resolvedPairs = selectedSegments.length > 0
    ? selectedSegments.map((segment) => ({
        profile: resolveProfileForSegment(segment),
        binding: resolveBindingForSegment(segment),
      }))
    : (input.timeline?.segment_entries
        .filter((entry) => input.segmentIds.includes(entry.segment_id))
        .map((entry) => ({
          profile: resolveProfileById(profileById, entry.render_profile_id),
          binding: resolveBindingById(bindingById, entry.voice_binding_id),
        })) ?? []);

  const profiles = resolvedPairs
    .map((pair) => pair.profile)
    .filter((profile): profile is RenderProfile => profile !== null);
  const bindings = resolvedPairs
    .map((pair) => pair.binding)
    .filter((binding): binding is VoiceBinding => binding !== null);
  const referenceStates = resolvedPairs.map((pair) =>
    resolveBindingReferenceState({
      binding: pair.binding,
      profile: pair.profile,
      bindingOptions: input.bindingOptions,
    }),
  );

  return {
    ...result,
    renderProfile: {
      speed: pickMixed(profiles.map((profile) => profile.speed)),
      top_k: pickMixed(profiles.map((profile) => profile.top_k)),
      top_p: pickMixed(profiles.map((profile) => profile.top_p)),
      temperature: pickMixed(profiles.map((profile) => profile.temperature)),
      noise_scale: pickMixed(profiles.map((profile) => profile.noise_scale)),
    },
    voiceBinding: {
      binding_ref: pickMixedBindingReference(bindings.map((binding) => binding.binding_ref ?? null)),
      voice_id: pickMixed(bindings.map((binding) => binding.voice_id)),
      model_key: pickMixed(bindings.map((binding) => binding.model_key)),
      gpt_path: pickMixed(bindings.map((binding) => binding.gpt_path)),
      sovits_path: pickMixed(bindings.map((binding) => binding.sovits_path)),
    },
    reference: pickReferenceState(referenceStates),
  };
}
