import type { InitializeRequest, RenderJobAcceptedResponse, RenderJobResponse } from '../types/editSession'
import { ensureTerminalStrongBoundary } from '../utils/textSegmenter.ts'

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
  customRefPath: string | null
}

export interface VoiceReferenceSource {
  refAudio?: string | null
}

const BOUNDARY_MODE_BY_TEXT_SPLIT_METHOD: Record<string, 'raw_strong_punctuation' | 'zh_period'> = {
  cut3: 'zh_period',
  cut5: 'zh_period',
  raw_strong_punctuation: 'raw_strong_punctuation',
  zh_period: 'zh_period',
}

export function normalizeSegmentBoundaryMode(mode: string): 'raw_strong_punctuation' | 'zh_period' {
  return BOUNDARY_MODE_BY_TEXT_SPLIT_METHOD[mode] ?? 'zh_period'
}

export function buildInitializeRequest(
  draft: WorkspaceInitializeDraft,
  voice?: VoiceReferenceSource,
): InitializeRequest {
  const payload: InitializeRequest = {
    raw_text: ensureTerminalStrongBoundary(draft.text),
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

  if (draft.refSource === 'custom' && draft.customRefPath) {
    payload.reference_audio_path = draft.customRefPath
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
