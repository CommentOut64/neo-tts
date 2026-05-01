import axios from './http'
import { resolveBackendUrl } from '@/platform/runtimeConfig'
import type {
  CleanupResidualsResponse,
  ForcePauseResponse,
  InferenceParamsCacheResponse,
  InferenceProgressState,
} from '@/types/tts'

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
