import axios from './http'
import { resolveBackendUrl } from '@/platform/runtimeConfig'
import type {
  CleanupResidualsResponse,
  DeleteSynthesisResultResponse,
  ForcePauseResponse,
  InferenceParamsCacheResponse,
  InferenceProgressState,
  SpeechRequest,
  SynthesizeSpeechResponse,
} from '@/types/tts'

export type SynthesizeSpeechParams = Pick<
  SpeechRequest,
  | 'input'
  | 'voice'
  | 'model'
  | 'response_format'
  | 'speed'
  | 'temperature'
  | 'top_p'
  | 'top_k'
  | 'pause_length'
  | 'text_lang'
  | 'text_split_method'
  | 'chunk_length'
  | 'history_window'
  | 'noise_scale'
  | 'sid'
  | 'ref_audio'
  | 'ref_audio_file'
  | 'ref_text'
  | 'ref_lang'
>

function readHeader(
  headers: Record<string, unknown> | { get?: (name: string) => string | undefined } | undefined,
  key: string,
): string | null {
  if (!headers) return null
  if (typeof (headers as { get?: (name: string) => string | undefined }).get === 'function') {
    const viaGet = (headers as { get: (name: string) => string | undefined }).get(key)
    if (typeof viaGet === 'string' && viaGet.length > 0) return viaGet
  }
  const map = headers as Record<string, unknown>
  const raw = map[key] ?? map[key.toLowerCase()]
  if (Array.isArray(raw)) return typeof raw[0] === 'string' ? raw[0] : null
  if (typeof raw === 'string') return raw
  return raw == null ? null : String(raw)
}

function buildSpeechFormData(params: SynthesizeSpeechParams): FormData {
  const form = new FormData()
  form.append('input', params.input)
  form.append('voice', params.voice)
  if (params.model !== undefined) form.append('model', params.model)
  if (params.response_format !== undefined) form.append('response_format', params.response_format)
  if (params.speed !== undefined) form.append('speed', String(params.speed))
  if (params.temperature !== undefined) form.append('temperature', String(params.temperature))
  if (params.top_p !== undefined) form.append('top_p', String(params.top_p))
  if (params.top_k !== undefined) form.append('top_k', String(params.top_k))
  if (params.pause_length !== undefined) form.append('pause_length', String(params.pause_length))
  if (params.text_lang !== undefined) form.append('text_lang', params.text_lang)
  if (params.text_split_method !== undefined) form.append('text_split_method', params.text_split_method)
  if (params.chunk_length !== undefined) form.append('chunk_length', String(params.chunk_length))
  if (params.history_window !== undefined) form.append('history_window', String(params.history_window))
  if (params.noise_scale !== undefined) form.append('noise_scale', String(params.noise_scale))
  if (params.sid !== undefined) form.append('sid', String(params.sid))
  if (params.ref_audio !== undefined) form.append('ref_audio', params.ref_audio)
  if (params.ref_text !== undefined) form.append('ref_text', params.ref_text)
  if (params.ref_lang !== undefined) form.append('ref_lang', params.ref_lang)
  if (params.ref_audio_file) form.append('ref_audio_file', params.ref_audio_file)
  return form
}



export async function synthesizeSpeechWithMeta(params: SynthesizeSpeechParams): Promise<SynthesizeSpeechResponse> {
  if (params.ref_audio_file) {
    const form = buildSpeechFormData(params)
    const response = await axios.post<Blob>('/v1/audio/speech', form, {
      responseType: 'blob',
      timeout: 0,
    })
    return {
      blob: response.data,
      taskId: readHeader(response.headers as Record<string, unknown>, 'x-inference-task-id'),
      resultId: readHeader(response.headers as Record<string, unknown>, 'x-synthesis-result-id'),
    }
  }
  const { ref_audio_file, ...jsonPayload } = params
  const response = await axios.post<Blob>('/v1/audio/speech', jsonPayload, {
    responseType: 'blob',
    timeout: 0,
  })
  return {
    blob: response.data,
    taskId: readHeader(response.headers as Record<string, unknown>, 'x-inference-task-id'),
    resultId: readHeader(response.headers as Record<string, unknown>, 'x-synthesis-result-id'),
  }
}

export async function synthesizeSpeech(params: SynthesizeSpeechParams): Promise<Blob> {
  const result = await synthesizeSpeechWithMeta(params)
  return result.blob
}

export async function getInferenceProgress(): Promise<InferenceProgressState> {
  const { data } = await axios.get<InferenceProgressState>('/v1/audio/inference/progress')
  return data
}

export function subscribeInferenceProgress(
  onProgress: (state: InferenceProgressState) => void,
  onError?: (error: Error) => void,
  options?: {
    onOpen?: () => void
  },
): () => void {
  const source = new EventSource(resolveBackendUrl('/v1/audio/inference/progress/stream'))

  const handleProgress = (event: MessageEvent<string>) => {
    try {
      const parsed = JSON.parse(event.data) as InferenceProgressState
      onProgress(parsed)
    } catch (error) {
      onError?.(error instanceof Error ? error : new Error(String(error)))
    }
  }

  source.addEventListener('progress', handleProgress as unknown as EventListener)
  source.onopen = () => {
    options?.onOpen?.()
  }
  source.onerror = () => {
    onError?.(new Error('推理进度 SSE 连接异常。'))
  }

  return () => {
    source.removeEventListener('progress', handleProgress as unknown as EventListener)
    source.close()
  }
}

export async function forcePauseInference(): Promise<ForcePauseResponse> {
  const { data } = await axios.post<ForcePauseResponse>('/v1/audio/inference/force-pause')
  return data
}

export async function cleanupInferenceResiduals(): Promise<CleanupResidualsResponse> {
  const { data } = await axios.post<CleanupResidualsResponse>('/v1/audio/inference/cleanup-residuals')
  return data
}

export async function deleteSynthesisResult(resultId: string): Promise<DeleteSynthesisResultResponse> {
  const { data } = await axios.delete<DeleteSynthesisResultResponse>(`/v1/audio/results/${resultId}`)
  return data
}

export async function getInferenceParamsCache(): Promise<InferenceParamsCacheResponse> {
  const { data } = await axios.get<InferenceParamsCacheResponse>('/v1/audio/inference/params-cache')
  return data
}

export async function putInferenceParamsCache(
  payload: Record<string, unknown>,
): Promise<InferenceParamsCacheResponse> {
  const { data } = await axios.put<InferenceParamsCacheResponse>('/v1/audio/inference/params-cache', { payload })
  return data
}
