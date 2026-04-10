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
let lifecycleDiagnosticsRegistered = false
let nextConsumerId = 0
const activeConsumers = new Map<number, string>()

function listActiveConsumers(): string[] {
  return Array.from(activeConsumers.values())
}

function buildRuntimeDiagnostics() {
  return {
    hasSubscription: unsubscribe !== null,
    isConnected: isProgressStreamConnected.value,
    runtimeError: runtimeError.value,
    progressStatus: progress.value.status,
    taskId: progress.value.task_id,
    visibilityState:
      typeof document !== 'undefined' ? document.visibilityState : 'unknown',
    activeConsumers: listActiveConsumers(),
  }
}

function warnRuntime(message: string, details: Record<string, unknown> = {}) {
  console.warn(`[useInferenceRuntime] ${message}`, {
    ...buildRuntimeDiagnostics(),
    ...details,
  })
}

function registerLifecycleDiagnostics() {
  if (lifecycleDiagnosticsRegistered) return
  if (typeof window === 'undefined' || typeof document === 'undefined') return

  const logLifecycleRestore = (event: 'visibilitychange' | 'pageshow') => {
    if (event === 'visibilitychange' && document.visibilityState !== 'visible') {
      return
    }
    warnRuntime(`page lifecycle event: ${event}`, {})
  }

  document.addEventListener('visibilitychange', () => {
    logLifecycleRestore('visibilitychange')
  })
  window.addEventListener('pageshow', () => {
    logLifecycleRestore('pageshow')
  })
  lifecycleDiagnosticsRegistered = true
}

function releaseProgressStreamSubscription(reason = 'unknown') {
  if (!unsubscribe) return
  warnRuntime('releasing inference progress subscription', { reason })
  const teardown = unsubscribe
  unsubscribe = null
  teardown()
}

function connectProgressStream(source = 'unknown') {
  if (unsubscribe) {
    warnRuntime('connectProgressStream skipped because a subscription already exists', {
      source,
    })
    return
  }
  warnRuntime('connecting inference progress stream', { source })
  runtimeError.value = null
  unsubscribe = subscribeInferenceProgress(
    (state) => {
      if (!isProgressStreamConnected.value) {
        warnRuntime('inference progress stream received event', {
          source,
          nextStatus: state.status,
          nextTaskId: state.task_id,
        })
      }
      progress.value = state
      isProgressStreamConnected.value = true
    },
    (error) => {
      warnRuntime('inference progress stream error', {
        source,
        error: error.message,
      })
      releaseProgressStreamSubscription(`error:${source}`)
      isProgressStreamConnected.value = false
      runtimeError.value = error.message
    },
  )
}

function disconnectProgressStream(source = 'unknown') {
  warnRuntime('disconnectProgressStream called', { source })
  releaseProgressStreamSubscription(`disconnect:${source}`)
  isProgressStreamConnected.value = false
}

export function useInferenceRuntime(ownerLabel = 'anonymous') {
  registerLifecycleDiagnostics()

  const consumerId = nextConsumerId++
  activeConsumers.set(consumerId, ownerLabel)
  warnRuntime('registered consumer', { ownerLabel })

  async function refreshProgress(source = ownerLabel): Promise<InferenceProgressState> {
    warnRuntime('refreshing inference progress snapshot', { source })
    const latest = await getInferenceProgress()
    progress.value = latest
    warnRuntime('received inference progress snapshot', {
      source,
      nextStatus: latest.status,
      nextTaskId: latest.task_id,
    })
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
    const remainingConsumers = listActiveConsumers().filter(
      (label) => label !== ownerLabel,
    )
    warnRuntime('consumer unmounting and requesting disconnect', {
      ownerLabel,
      remainingConsumers,
    })
    activeConsumers.delete(consumerId)
    disconnectProgressStream(`${ownerLabel}:onBeforeUnmount`)
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
