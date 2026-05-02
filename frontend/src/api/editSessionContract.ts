import type {
  BindingReference,
  InitializeRequest,
  RenderJobAcceptedResponse,
  RenderJobResponse,
  ExportJobAcceptedResponse,
  ExportJobResponse,
} from "../types/editSession";

export interface WorkspaceInitializeDraft {
  text: string;
  voiceId?: string;
  bindingRef?: BindingReference;
  textLang: string;
  speed: number;
  temperature: number;
  topP: number;
  topK: number;
  noiseScale: number;
  pauseLength: number;
  refSource: "preset" | "custom";
  refText: string;
  refLang: string;
  customRefFile: File | null;
  customRefPath: string | null;
}

export interface BindingReferenceSource {
  refAudio?: string | null;
}

export const WORKSPACE_SEGMENT_BOUNDARY_MODE = "raw_strong_punctuation" as const;

export function buildInitializeRequest(
  draft: WorkspaceInitializeDraft,
  binding?: BindingReferenceSource,
): InitializeRequest {
  const bindingRef: BindingReference = draft.bindingRef ?? {
    workspace_id: "legacy",
    main_model_id: draft.voiceId ?? "default",
    submodel_id: "gpt-sovits-v2",
    preset_id: "default",
  };
  const payload: InitializeRequest = {
    raw_text: draft.text,
    text_language: draft.textLang,
    binding_ref: bindingRef,
    reference_source: draft.refSource,
    speed: draft.speed,
    temperature: draft.temperature,
    top_p: draft.topP,
    top_k: draft.topK,
    noise_scale: draft.noiseScale,
    pause_duration_seconds: draft.pauseLength,
    segment_boundary_mode: WORKSPACE_SEGMENT_BOUNDARY_MODE,
  };

  if (draft.refSource === "preset" && binding?.refAudio) {
    payload.reference_audio_path = binding.refAudio;
  }

  if (draft.refSource === "custom" && draft.customRefPath) {
    payload.reference_audio_path = draft.customRefPath;
  }

  if (draft.refText.trim().length > 0) {
    payload.reference_text = draft.refText;
  }

  if (draft.refLang.trim().length > 0) {
    payload.reference_language = draft.refLang;
  }

  return payload;
}

export function unwrapAcceptedRenderJob(
  response: RenderJobAcceptedResponse,
): RenderJobResponse {
  return response.job;
}

export function unwrapAcceptedExportJob(
  response: ExportJobAcceptedResponse,
): ExportJobResponse {
  return response.job;
}
