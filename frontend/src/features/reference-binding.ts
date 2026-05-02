import type {
  BindingReference,
  RenderProfile,
  VoiceBinding,
} from "@/types/editSession";
import type {
  RegistryBindingOption,
} from "@/types/ttsRegistry";

export interface ReferenceSelectionByBindingEntry {
  source: "preset" | "custom";
  session_reference_asset_id?: string | null;
  custom_ref_path: string | null;
  ref_text: string;
  ref_lang: string;
}

export type ReferenceSelectionByBinding = Record<string, ReferenceSelectionByBindingEntry>;

export interface ResolvedBindingReferenceState {
  source: "preset" | "custom" | null;
  reference_scope: "voice_preset" | "session_override" | null;
  binding_key: string | null;
  reference_identity: string | null;
  session_reference_asset_id: string | null;
  reference_audio_fingerprint: string | null;
  reference_audio_path: string | null;
  reference_text: string | null;
  reference_text_fingerprint: string | null;
  reference_language: string | null;
  preset_audio_path: string | null;
  preset_text: string | null;
  preset_language: string | null;
}

export function buildReferenceBindingKey(input: {
  bindingRef?: BindingReference | null;
  voiceId?: string | null;
  modelKey?: string | null;
}): string {
  if (input.bindingRef) {
    return [
      input.bindingRef.workspace_id,
      input.bindingRef.main_model_id,
      input.bindingRef.submodel_id,
      input.bindingRef.preset_id,
    ].join(":");
  }
  return `${input.voiceId ?? ""}:${input.modelKey ?? ""}`;
}

export function buildReferenceSelectionEntry(input: {
  source: "preset" | "custom";
  sessionReferenceAssetId?: string | null;
  customRefPath: string | null;
  refText: string;
  refLang: string;
}): ReferenceSelectionByBindingEntry {
  return {
    source: input.source,
    session_reference_asset_id: input.sessionReferenceAssetId ?? null,
    custom_ref_path: input.customRefPath,
    ref_text: input.refText,
    ref_lang: input.refLang,
  };
}

export function resolveBindingReferenceState(input: {
  binding: Pick<VoiceBinding, "voice_id" | "model_key" | "binding_ref"> | null;
  profile: Pick<RenderProfile, "reference_overrides_by_binding"> | null;
  bindingOptions: RegistryBindingOption[];
}): ResolvedBindingReferenceState {
  const bindingOptions = input.bindingOptions ?? [];
  if (!input.binding?.binding_ref && (!input.binding?.voice_id || !input.binding.model_key)) {
    return buildEmptyResolvedBindingReferenceState();
  }

  const bindingKey = buildReferenceBindingKey({
    bindingRef: input.binding.binding_ref,
    voiceId: input.binding.voice_id ?? "",
    modelKey: input.binding.model_key ?? "",
  });
  const override = input.profile?.reference_overrides_by_binding?.[bindingKey] ?? null;
  const bindingOption = bindingOptions.find((item) => item.bindingKey === bindingKey) ?? null;

  return {
    source: override ? "custom" : "preset",
    reference_scope: override ? "session_override" : "voice_preset",
    binding_key: bindingKey,
    reference_identity: override
      ? override.reference_identity
        ?? (override.session_reference_asset_id
          ? `session-override:${override.session_reference_asset_id}`
          : bindingKey)
      : `${bindingKey}:preset`,
    session_reference_asset_id: override?.session_reference_asset_id ?? null,
    reference_audio_fingerprint: override?.reference_audio_fingerprint ?? null,
    reference_audio_path: override?.reference_audio_path ?? bindingOption?.referenceAudioPath ?? null,
    reference_text: override?.reference_text ?? bindingOption?.referenceText ?? null,
    reference_text_fingerprint: override?.reference_text_fingerprint ?? null,
    reference_language: override?.reference_language ?? bindingOption?.referenceLanguage ?? null,
    preset_audio_path: bindingOption?.referenceAudioPath ?? null,
    preset_text: bindingOption?.referenceText ?? null,
    preset_language: bindingOption?.referenceLanguage ?? null,
  };
}

export function resolveReferenceSelectionForBinding(input: {
  bindingRef?: BindingReference | null;
  voiceId?: string | null;
  modelKey?: string | null;
  bindingOptions: RegistryBindingOption[];
  selections: ReferenceSelectionByBinding;
}): {
  bindingKey: string;
  selection: ReferenceSelectionByBindingEntry;
} {
  const bindingOptions = input.bindingOptions ?? [];
  const bindingKey = buildReferenceBindingKey({
    bindingRef: input.bindingRef,
    voiceId: input.voiceId,
    modelKey: input.modelKey,
  });
  const cachedSelection = input.selections[bindingKey];
  const bindingOption = bindingOptions.find((item) => item.bindingKey === bindingKey) ?? null;

  if (cachedSelection?.source === "custom") {
    return {
      bindingKey,
      selection: cachedSelection,
    };
  }

  return {
    bindingKey,
    selection: buildPresetReferenceSelectionEntry(bindingOption),
  };
}

export function resolveReferenceSelectionBySource(input: {
  bindingRef?: BindingReference | null;
  voiceId?: string | null;
  modelKey?: string | null;
  source: "preset" | "custom";
  bindingOptions: RegistryBindingOption[];
  selections: ReferenceSelectionByBinding;
}): {
  bindingKey: string;
  selection: ReferenceSelectionByBindingEntry;
} {
  const bindingOptions = input.bindingOptions ?? [];
  const bindingKey = buildReferenceBindingKey({
    bindingRef: input.bindingRef,
    voiceId: input.voiceId,
    modelKey: input.modelKey,
  });
  const bindingOption = bindingOptions.find((item) => item.bindingKey === bindingKey) ?? null;

  if (input.source === "preset") {
    return {
      bindingKey,
      selection: buildPresetReferenceSelectionEntry(bindingOption),
    };
  }

  const cachedSelection = input.selections[bindingKey];
  if (cachedSelection?.source === "custom") {
    return {
      bindingKey,
      selection: cachedSelection,
    };
  }

  return {
    bindingKey,
    selection: buildReferenceSelectionEntry({
      source: "custom",
      sessionReferenceAssetId: null,
      customRefPath: null,
      refText: bindingOption?.referenceText ?? "",
      refLang: bindingOption?.referenceLanguage ?? "auto",
    }),
  };
}

export function upsertReferenceSelectionByBinding(input: {
  selections: ReferenceSelectionByBinding;
  bindingRef?: BindingReference | null;
  voiceId?: string | null;
  modelKey?: string | null;
  entry: ReferenceSelectionByBindingEntry;
}): ReferenceSelectionByBinding {
  const bindingKey = buildReferenceBindingKey({
    bindingRef: input.bindingRef,
    voiceId: input.voiceId,
    modelKey: input.modelKey,
  });

  return {
    ...input.selections,
    [bindingKey]: input.entry,
  };
}

export function upgradeInferenceParamsCachePayload(
  payload: Record<string, unknown>,
): Record<string, unknown> {
  const upgradedPayload: Record<string, unknown> = { ...payload };
  const normalizedSelections = normalizeReferenceSelectionsByBinding(
    payload.referenceSelectionsByBinding,
  );

  if (Object.keys(normalizedSelections).length === 0) {
    const voiceId = readString(payload.voice_id) ?? readString(payload.voice);
    const refSource = readReferenceSource(payload.ref_source);
    const refText = readString(payload.ref_text) ?? readString(payload.refText);
    const refLang = readString(payload.ref_lang) ?? readString(payload.refLang);
    const customRefPath = readNullableString(payload.custom_ref_path);

    if (voiceId && refSource) {
      normalizedSelections[
        buildReferenceBindingKey({
          voiceId,
          modelKey: readString(payload.model_key) ?? "gpt-sovits-v2",
        })
      ] = {
        source: refSource,
        session_reference_asset_id: null,
        custom_ref_path: customRefPath,
        ref_text: refText ?? "",
        ref_lang: refLang ?? "auto",
      };
    }
  }

  upgradedPayload.referenceSelectionsByBinding = normalizedSelections;
  return upgradedPayload;
}

function buildPresetReferenceSelectionEntry(
  bindingOption: RegistryBindingOption | null,
): ReferenceSelectionByBindingEntry {
  return buildReferenceSelectionEntry({
    source: "preset",
    sessionReferenceAssetId: null,
    customRefPath: null,
    refText: bindingOption?.referenceText ?? "",
    refLang: bindingOption?.referenceLanguage ?? "auto",
  });
}

function buildEmptyResolvedBindingReferenceState(): ResolvedBindingReferenceState {
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

function normalizeReferenceSelectionsByBinding(
  raw: unknown,
): ReferenceSelectionByBinding {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return {};
  }

  const normalizedEntries = Object.entries(raw).flatMap(([bindingKey, value]) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return [];
    }

    const source = readReferenceSource((value as Record<string, unknown>).source);
    if (!source) {
      return [];
    }

    return [[bindingKey, {
      source,
      session_reference_asset_id: readNullableString((value as Record<string, unknown>).session_reference_asset_id),
      custom_ref_path: readNullableString((value as Record<string, unknown>).custom_ref_path),
      ref_text: readString((value as Record<string, unknown>).ref_text) ?? "",
      ref_lang: readString((value as Record<string, unknown>).ref_lang) ?? "auto",
    } satisfies ReferenceSelectionByBindingEntry]];
  });

  return Object.fromEntries(normalizedEntries);
}

function readString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function readNullableString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function readReferenceSource(value: unknown): "preset" | "custom" | null {
  return value === "preset" || value === "custom" ? value : null;
}
