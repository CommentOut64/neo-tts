import type { InitializeRequest, RenderJobAcceptedResponse, RenderJobResponse } from '../types/editSession'

export interface WorkspaceInitializeDraft {
  text: string
  voiceId: string
  textLang: string
  speed: number
  temperature: number
  topP: number
  topK: number
  pauseLength: number
  textSplitMethod: string
  refSource: 'preset' | 'custom'
  refText: string
  refLang: string
  customRefFile: File | null
}

export interface VoiceReferenceSource {
  refAudio?: string | null
}

const SUPPORTED_BOUNDARY_MODES = new Set(['raw_strong_punctuation', 'zh_period'])

export function normalizeSegmentBoundaryMode(mode: string): 'raw_strong_punctuation' | 'zh_period' {
  return SUPPORTED_BOUNDARY_MODES.has(mode)
    ? (mode as 'raw_strong_punctuation' | 'zh_period')
    : 'raw_strong_punctuation'
}

export function buildInitializeRequest(
  draft: WorkspaceInitializeDraft,
  voice?: VoiceReferenceSource,
): InitializeRequest {
  const payload: InitializeRequest = {
    raw_text: draft.text,
    text_language: draft.textLang,
    voice_id: draft.voiceId,
    speed: draft.speed,
    temperature: draft.temperature,
    top_p: draft.topP,
    top_k: draft.topK,
    pause_duration_seconds: draft.pauseLength,
    segment_boundary_mode: normalizeSegmentBoundaryMode(draft.textSplitMethod),
  }

  if (draft.refSource === 'preset' && voice?.refAudio) {
    payload.reference_audio_path = voice.refAudio
  }

  if (draft.refText.trim().length > 0) {
    payload.reference_text = draft.refText
  }

  if (draft.refLang.trim().length > 0) {
    payload.reference_language = draft.refLang
  }

  return payload
}

export function unwrapAcceptedRenderJob(response: RenderJobAcceptedResponse): RenderJobResponse {
  return response.job
}
