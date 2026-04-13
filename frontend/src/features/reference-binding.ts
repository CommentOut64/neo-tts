import type {
  RenderProfile,
  VoiceBinding,
} from "@/types/editSession";
import type {
  ReferenceSelectionByBinding,
  ReferenceSelectionByBindingEntry,
  VoiceProfile,
} from "@/types/tts";

export const DEFAULT_REFERENCE_BINDING_MODEL_KEY = "gpt-sovits-v2";

export interface ResolvedBindingReferenceState {
  source: "preset" | "custom" | null;
  binding_key: string | null;
  reference_audio_path: string | null;
  reference_text: string | null;
  reference_language: string | null;
  preset_audio_path: string | null;
  preset_text: string | null;
  preset_language: string | null;
}

export function buildReferenceBindingKey({
  voiceId,
  modelKey,
}: {
  voiceId: string;
  modelKey: string;
}): string {
  return `${voiceId}:${modelKey}`;
}

export function resolveBindingReferenceState(input: {
  binding: Pick<VoiceBinding, "voice_id" | "model_key"> | null;
  profile: Pick<RenderProfile, "reference_overrides_by_binding"> | null;
  voices: VoiceProfile[];
}): ResolvedBindingReferenceState {
  if (!input.binding?.voice_id || !input.binding.model_key) {
    return buildEmptyResolvedBindingReferenceState();
  }

  const voice = input.voices.find((item) => item.name === input.binding?.voice_id) ?? null;
  const bindingKey = buildReferenceBindingKey({
    voiceId: input.binding.voice_id,
    modelKey: input.binding.model_key,
  });
  const override = input.profile?.reference_overrides_by_binding?.[bindingKey] ?? null;

  return {
    source: override ? "custom" : "preset",
    binding_key: bindingKey,
    reference_audio_path: override?.reference_audio_path ?? voice?.ref_audio ?? null,
    reference_text: override?.reference_text ?? voice?.ref_text ?? null,
    reference_language: override?.reference_language ?? voice?.ref_lang ?? null,
    preset_audio_path: voice?.ref_audio ?? null,
    preset_text: voice?.ref_text ?? null,
    preset_language: voice?.ref_lang ?? null,
  };
}

export function buildReferenceSelectionEntry(input: {
  source: "preset" | "custom";
  customRefPath: string | null;
  refText: string;
  refLang: string;
}): ReferenceSelectionByBindingEntry {
  return {
    source: input.source,
    custom_ref_path: input.customRefPath,
    ref_text: input.refText,
    ref_lang: input.refLang,
  };
}

function buildPresetReferenceSelectionEntry(
  voice: VoiceProfile | null,
): ReferenceSelectionByBindingEntry {
  return buildReferenceSelectionEntry({
    source: "preset",
    customRefPath: null,
    refText: voice?.ref_text ?? "",
    refLang: voice?.ref_lang ?? "auto",
  });
}

export function resolveReferenceSelectionForBinding(input: {
  voiceId: string;
  modelKey?: string | null;
  voices: VoiceProfile[];
  selections: ReferenceSelectionByBinding;
}): {
  bindingKey: string;
  selection: ReferenceSelectionByBindingEntry;
} {
  const modelKey = input.modelKey || DEFAULT_REFERENCE_BINDING_MODEL_KEY;
  const bindingKey = buildReferenceBindingKey({
    voiceId: input.voiceId,
    modelKey,
  });
  const cachedSelection = input.selections[bindingKey];
  const voice = input.voices.find((item) => item.name === input.voiceId) ?? null;

  if (cachedSelection?.source === "custom") {
    return {
      bindingKey,
      selection: cachedSelection,
    };
  }

  return {
    bindingKey,
    selection: buildPresetReferenceSelectionEntry(voice),
  };
}

export function resolveReferenceSelectionBySource(input: {
  voiceId: string;
  source: "preset" | "custom";
  modelKey?: string | null;
  voices: VoiceProfile[];
  selections: ReferenceSelectionByBinding;
}): {
  bindingKey: string;
  selection: ReferenceSelectionByBindingEntry;
} {
  const modelKey = input.modelKey || DEFAULT_REFERENCE_BINDING_MODEL_KEY;
  const bindingKey = buildReferenceBindingKey({
    voiceId: input.voiceId,
    modelKey,
  });
  const voice = input.voices.find((item) => item.name === input.voiceId) ?? null;

  if (input.source === "preset") {
    return {
      bindingKey,
      selection: buildPresetReferenceSelectionEntry(voice),
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
      customRefPath: null,
      refText: voice?.ref_text ?? "",
      refLang: voice?.ref_lang ?? "auto",
    }),
  };
}

export function upsertReferenceSelectionByBinding(input: {
  selections: ReferenceSelectionByBinding;
  voiceId: string;
  modelKey?: string | null;
  entry: ReferenceSelectionByBindingEntry;
}): ReferenceSelectionByBinding {
  const modelKey = input.modelKey || DEFAULT_REFERENCE_BINDING_MODEL_KEY;
  const bindingKey = buildReferenceBindingKey({
    voiceId: input.voiceId,
    modelKey,
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
          modelKey: DEFAULT_REFERENCE_BINDING_MODEL_KEY,
        })
      ] = {
        source: refSource,
        custom_ref_path: customRefPath,
        ref_text: refText ?? "",
        ref_lang: refLang ?? "auto",
      };
    }
  }

  upgradedPayload.referenceSelectionsByBinding = normalizedSelections;
  return upgradedPayload;
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

    return [[
      bindingKey,
      {
        source,
        custom_ref_path: readNullableString(
          (value as Record<string, unknown>).custom_ref_path,
        ),
        ref_text: readString((value as Record<string, unknown>).ref_text) ?? "",
        ref_lang: readString((value as Record<string, unknown>).ref_lang) ?? "auto",
      },
    ]] as const;
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

function buildEmptyResolvedBindingReferenceState(): ResolvedBindingReferenceState {
  return {
    source: null,
    binding_key: null,
    reference_audio_path: null,
    reference_text: null,
    reference_language: null,
    preset_audio_path: null,
    preset_text: null,
    preset_language: null,
  };
}
