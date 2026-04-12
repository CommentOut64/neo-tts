import type { ReferenceSelectionByBinding } from "@/types/tts";

export const DEFAULT_REFERENCE_BINDING_MODEL_KEY = "gpt-sovits-v2";

export function buildReferenceBindingKey({
  voiceId,
  modelKey,
}: {
  voiceId: string;
  modelKey: string;
}): string {
  return `${voiceId}:${modelKey}`;
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
