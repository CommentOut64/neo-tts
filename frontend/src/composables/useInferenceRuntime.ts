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

const ACTIVE_PROGRESS_STATUSES = new Set(['preparing', 'inferencing', 'cancelling'])
const PROGRESS_RECONNECT_DELAYS_MS = [800, 1600, 3200]
const PROGRESS_HEALTH_CHECK_INTERVAL_MS = 5000
const PROGRESS_STREAM_STALE_MS = 30000

// 模块级单例状态（与 useTheme 模式一致）
const progress = ref<InferenceProgressState>({ ...IDLE_PROGRESS })
const isProgressStreamConnected = ref(false)
const runtimeError = ref<string | null>(null)
let unsubscribe: (() => void) | null = null
let lifecycleDiagnosticsRegistered = false
let nextConsumerId = 0
const activeConsumers = new Map<number, string>()
let reconnectTimerId: ReturnType<typeof setTimeout> | null = null
let reconnectAttempt = 0
let healthCheckIntervalId: ReturnType<typeof setInterval> | null = null
let refreshInFlight: Promise<InferenceProgressState> | null = null
let lastProgressStreamActivityAt = 0

function listActiveConsumers(): string[] {
  return Array.from(activeConsumers.values())
}

function hasActiveConsumers(): boolean {
  return activeConsumers.size > 0
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
    lastProgressStreamActivityAt,
  }
}

function warnRuntime(message: string, details: Record<string, unknown> = {}) {
  console.warn(`[useInferenceRuntime] ${message}`, {
    ...buildRuntimeDiagnostics(),
    ...details,
  })
}

function isPageVisible(): boolean {
  return typeof document === 'undefined' || document.visibilityState === 'visible'
}

function clearReconnectTimer() {
  if (reconnectTimerId === null) return
  clearTimeout(reconnectTimerId)
  reconnectTimerId = null
}

function clearHealthCheckInterval() {
  if (healthCheckIntervalId === null) return
  clearInterval(healthCheckIntervalId)
  healthCheckIntervalId = null
}

function markProgressStreamActivity() {
  lastProgressStreamActivityAt = Date.now()
}

function refreshProgressInBackground(source: string) {
  void refreshProgressInternal(source, { warn: false }).catch((error) => {
    const message = error instanceof Error ? error.message : String(error)
    runtimeError.value = message
    warnRuntime('failed to refresh inference progress snapshot', {
      source,
      error: message,
    })
  })
}

async function refreshProgressInternal(
  source: string,
  options: { warn?: boolean } = {},
): Promise<InferenceProgressState> {
  const shouldWarn = options.warn ?? true
  if (refreshInFlight) {
    if (shouldWarn) {
      warnRuntime('refreshProgress reused in-flight request', { source })
    }
    return refreshInFlight
  }

  if (shouldWarn) {
    warnRuntime('refreshing inference progress snapshot', { source })
  }

  refreshInFlight = Promise.resolve()
    .then(() => getInferenceProgress())
    .then((latest) => {
      progress.value = latest
      if (shouldWarn) {
        warnRuntime('received inference progress snapshot', {
          source,
          nextStatus: latest.status,
          nextTaskId: latest.task_id,
        })
      }
      return latest
    })
    .finally(() => {
      refreshInFlight = null
    })

  return refreshInFlight
}

function scheduleReconnect(reason: string) {
  if (!hasActiveConsumers()) {
    warnRuntime('skip scheduling reconnect because there are no active consumers', {
      reason,
    })
    return
  }
  if (reconnectTimerId !== null) {
    warnRuntime('reconnect already scheduled', {
      reason,
      attempt: reconnectAttempt,
    })
    return
  }

  const attempt = reconnectAttempt + 1
  reconnectAttempt = attempt
  const delay =
    PROGRESS_RECONNECT_DELAYS_MS[
      Math.min(attempt - 1, PROGRESS_RECONNECT_DELAYS_MS.length - 1)
    ]

  warnRuntime('scheduling inference progress reconnect', {
    reason,
    attempt,
    delayMs: delay,
  })

  reconnectTimerId = setTimeout(() => {
    reconnectTimerId = null
    connectProgressStream(`reconnect#${attempt}:${reason}`)
    refreshProgressInBackground(`reconnect#${attempt}:${reason}`)
  }, delay)
}

function ensureHealthCheckLoop() {
  if (!hasActiveConsumers()) {
    clearHealthCheckInterval()
    return
  }
  if (healthCheckIntervalId !== null) return

  healthCheckIntervalId = setInterval(() => {
    if (!hasActiveConsumers() || !isPageVisible()) {
      return
    }

    if (unsubscribe === null || !isProgressStreamConnected.value) {
      warnRuntime('health check detected missing or disconnected inference progress stream', {})
      connectProgressStream('health-check')
      refreshProgressInBackground('health-check')
      return
    }

    const isActiveStatus = ACTIVE_PROGRESS_STATUSES.has(progress.value.status)
    const streamInactiveForMs =
      lastProgressStreamActivityAt > 0 ? Date.now() - lastProgressStreamActivityAt : null
    if (
      isActiveStatus &&
      streamInactiveForMs !== null &&
      streamInactiveForMs >= PROGRESS_STREAM_STALE_MS
    ) {
      warnRuntime('health check detected stale inference progress stream', {
        streamInactiveForMs,
      })
      releaseProgressStreamSubscription('health-check:stale')
      isProgressStreamConnected.value = false
      scheduleReconnect('health-check:stale')
      refreshProgressInBackground('health-check:stale')
      return
    }

    if (isActiveStatus) {
      refreshProgressInBackground('health-check')
    }
  }, PROGRESS_HEALTH_CHECK_INTERVAL_MS)
}

function registerLifecycleDiagnostics() {
  if (lifecycleDiagnosticsRegistered) return
  if (typeof window === 'undefined' || typeof document === 'undefined') return

  const logLifecycleRestore = (event: 'visibilitychange' | 'pageshow') => {
    if (event === 'visibilitychange' && document.visibilityState !== 'visible') {
      return
    }
    warnRuntime(`page lifecycle event: ${event}`, {})
    if (hasActiveConsumers()) {
      connectProgressStream(`lifecycle:${event}`)
      refreshProgressInBackground(`lifecycle:${event}`)
    }
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
    if (isProgressStreamConnected.value) {
      warnRuntime('connectProgressStream skipped because a healthy subscription already exists', {
        source,
      })
      return
    }
    warnRuntime('replacing stale inference progress subscription before reconnect', {
      source,
    })
    releaseProgressStreamSubscription(`replace:${source}`)
  }

  clearReconnectTimer()
  warnRuntime('connecting inference progress stream', { source })
  runtimeError.value = null
  isProgressStreamConnected.value = false
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
      reconnectAttempt = 0
      markProgressStreamActivity()
    },
    (error) => {
      warnRuntime('inference progress stream error', {
        source,
        error: error.message,
      })
      releaseProgressStreamSubscription(`error:${source}`)
      isProgressStreamConnected.value = false
      runtimeError.value = error.message
      scheduleReconnect(`error:${source}`)
    },
    {
      onOpen: () => {
        reconnectAttempt = 0
        isProgressStreamConnected.value = true
        markProgressStreamActivity()
        warnRuntime('inference progress stream opened', { source })
      },
    },
  )
  ensureHealthCheckLoop()
}

function disconnectProgressStream(source = 'unknown') {
  warnRuntime('disconnectProgressStream called', { source })
  clearReconnectTimer()
  releaseProgressStreamSubscription(`disconnect:${source}`)
  isProgressStreamConnected.value = false
  lastProgressStreamActivityAt = 0
  reconnectAttempt = 0
  if (!hasActiveConsumers()) {
    clearHealthCheckInterval()
  }
}

export function useInferenceRuntime(ownerLabel = 'anonymous') {
  registerLifecycleDiagnostics()

  const consumerId = nextConsumerId++
  activeConsumers.set(consumerId, ownerLabel)
  warnRuntime('registered consumer', { ownerLabel })
  ensureHealthCheckLoop()

  async function refreshProgress(source = ownerLabel): Promise<InferenceProgressState> {
    return refreshProgressInternal(source)
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
    activeConsumers.delete(consumerId)
    const remainingConsumers = listActiveConsumers()
    warnRuntime('consumer unmounting and requesting disconnect', {
      ownerLabel,
      remainingConsumers,
    })
    if (remainingConsumers.length === 0) {
      disconnectProgressStream(`${ownerLabel}:onBeforeUnmount`)
      clearHealthCheckInterval()
      return
    }
    warnRuntime('preserving inference progress stream because other consumers are still active', {
      ownerLabel,
      remainingConsumers,
    })
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
