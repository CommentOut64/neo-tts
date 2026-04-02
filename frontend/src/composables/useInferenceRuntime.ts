import { onBeforeUnmount, ref } from 'vue'
import {
  cleanupInferenceResiduals,
  forcePauseInference,
  getInferenceProgress,
  subscribeInferenceProgress,
} from '@/api/tts'
import type { CleanupResidualsResponse, ForcePauseResponse, InferenceProgressState } from '@/types/tts'

const IDLE_PROGRESS: InferenceProgressState = {
  task_id: null,
  status: 'idle',
  progress: 0,
  message: '',
  cancel_requested: false,
  current_segment: null,
  total_segments: null,
  result_id: null,
  updated_at: new Date(0).toISOString(),
}

// 模块级单例状态（与 useTheme 模式一致）
const progress = ref<InferenceProgressState>({ ...IDLE_PROGRESS })
const isProgressStreamConnected = ref(false)
const runtimeError = ref<string | null>(null)
let unsubscribe: (() => void) | null = null

function connectProgressStream() {
  if (unsubscribe) return
  runtimeError.value = null
  unsubscribe = subscribeInferenceProgress(
    (state) => {
      progress.value = state
      isProgressStreamConnected.value = true
    },
    (error) => {
      isProgressStreamConnected.value = false
      runtimeError.value = error.message
    },
  )
}

function disconnectProgressStream() {
  if (!unsubscribe) return
  unsubscribe()
  unsubscribe = null
  isProgressStreamConnected.value = false
}

export function useInferenceRuntime() {
  async function refreshProgress(): Promise<InferenceProgressState> {
    const latest = await getInferenceProgress()
    progress.value = latest
    return latest
  }

  async function requestForcePause(): Promise<ForcePauseResponse> {
    const result = await forcePauseInference()
    progress.value = result.state
    return result
  }

  async function requestCleanupResiduals(): Promise<CleanupResidualsResponse> {
    const result = await cleanupInferenceResiduals()
    progress.value = result.state
    return result
  }

  function clearRuntimeError() {
    runtimeError.value = null
  }

  onBeforeUnmount(() => {
    disconnectProgressStream()
  })

  return {
    progress,
    isProgressStreamConnected,
    runtimeError,
    refreshProgress,
    connectProgressStream,
    disconnectProgressStream,
    requestForcePause,
    requestCleanupResiduals,
    clearRuntimeError,
  }
}
