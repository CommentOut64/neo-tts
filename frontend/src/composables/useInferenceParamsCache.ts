import { ref } from 'vue'
import { getInferenceParamsCache, putInferenceParamsCache } from '@/api/tts'
import { upgradeInferenceParamsCachePayload } from '@/features/reference-binding'
import type { InferenceParamsCacheEnvelope } from '@/types/tts'

const STORAGE_KEY = 'gpt-sovits-inference-params-cache'

type IdleWindow = Window & {
  requestIdleCallback?: (callback: () => void, options?: { timeout?: number }) => number
  cancelIdleCallback?: (id: number) => void
}

function hasBrowserStorage(): boolean {
  return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined'
}

function scheduleWhenIdle(task: () => Promise<void> | void): () => void {
  const win = window as IdleWindow
  if (typeof win.requestIdleCallback === 'function') {
    const id = win.requestIdleCallback(() => {
      void task()
    }, { timeout: 2_000 })
    return () => {
      if (typeof win.cancelIdleCallback === 'function') {
        win.cancelIdleCallback(id)
      }
    }
  }

  const timeoutId = window.setTimeout(() => {
    void task()
  }, 250)
  return () => window.clearTimeout(timeoutId)
}

function normalizeEnvelope(raw: unknown): InferenceParamsCacheEnvelope | null {
  if (!raw || typeof raw !== 'object') return null
  const payload = (raw as { payload?: unknown }).payload
  const updatedAt = (raw as { updatedAt?: unknown }).updatedAt
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null
  if (updatedAt !== null && updatedAt !== undefined && typeof updatedAt !== 'string') return null
  return {
    payload: upgradeInferenceParamsCachePayload(payload as Record<string, unknown>),
    updatedAt: (updatedAt as string | null | undefined) ?? null,
  }
}

export function useInferenceParamsCache() {
  const lastSyncedAt = ref<string | null>(null)
  const cacheError = ref<string | null>(null)
  let cancelIdleTask: (() => void) | null = null
  let putInFlight = false
  let pendingPayload: Record<string, unknown> | null = null

  function readLocalCache(): InferenceParamsCacheEnvelope | null {
    if (!hasBrowserStorage()) return null
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    try {
      const parsed = JSON.parse(raw)
      return normalizeEnvelope(parsed)
    } catch {
      window.localStorage.removeItem(STORAGE_KEY)
      return null
    }
  }

  function saveLocalCache(payload: Record<string, unknown>, updatedAt: string | null = null): InferenceParamsCacheEnvelope {
    const envelope: InferenceParamsCacheEnvelope = {
      payload: upgradeInferenceParamsCachePayload(payload),
      updatedAt,
    }
    if (hasBrowserStorage()) {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(envelope))
    }
    return envelope
  }

  async function restoreCache(): Promise<InferenceParamsCacheEnvelope | null> {
    const local = readLocalCache()
    if (local) {
      const upgradedLocal = saveLocalCache(local.payload, local.updatedAt)
      lastSyncedAt.value = upgradedLocal.updatedAt
      return upgradedLocal
    }

    try {
      const remote = await getInferenceParamsCache()
      if (!remote.payload || Object.keys(remote.payload).length === 0) return null
      const envelope = saveLocalCache(remote.payload, remote.updated_at)
      lastSyncedAt.value = envelope.updatedAt
      return envelope
    } catch (error) {
      cacheError.value = error instanceof Error ? error.message : String(error)
      return null
    }
  }

  async function flushToRemote(payload: Record<string, unknown>): Promise<void> {
    const upgradedPayload = upgradeInferenceParamsCachePayload(payload)
    putInFlight = true
    pendingPayload = null
    try {
      const remote = await putInferenceParamsCache(upgradedPayload)
      lastSyncedAt.value = remote.updated_at
      saveLocalCache(upgradedPayload, remote.updated_at)
      cacheError.value = null
    } catch (error) {
      cacheError.value = error instanceof Error ? error.message : String(error)
    } finally {
      putInFlight = false
      // PUT 完成后若有新 pending，立即再发一次（只发最新值）
      if (pendingPayload) {
        const next = pendingPayload
        pendingPayload = null
        await flushToRemote(next)
      }
    }
  }

  function persistCacheWhenIdle(payload: Record<string, unknown>) {
    const upgradedPayload = saveLocalCache(payload, lastSyncedAt.value).payload
    cacheError.value = null

    // PUT 进行中时只暂存最新 payload，等当前 PUT 完成后再发
    if (putInFlight) {
      pendingPayload = upgradedPayload
      return
    }

    if (cancelIdleTask) {
      cancelIdleTask()
      cancelIdleTask = null
    }

    cancelIdleTask = scheduleWhenIdle(async () => {
      cancelIdleTask = null
      await flushToRemote(upgradedPayload)
    })
  }

  async function persistCacheNow(payload: Record<string, unknown>): Promise<InferenceParamsCacheEnvelope> {
    const upgradedPayload = saveLocalCache(payload, lastSyncedAt.value).payload
    const remote = await putInferenceParamsCache(upgradedPayload)
    lastSyncedAt.value = remote.updated_at
    cacheError.value = null
    return saveLocalCache(upgradedPayload, remote.updated_at)
  }

  function clearLocalCache() {
    if (hasBrowserStorage()) {
      window.localStorage.removeItem(STORAGE_KEY)
    }
    lastSyncedAt.value = null
    cacheError.value = null
  }

  return {
    lastSyncedAt,
    cacheError,
    readLocalCache,
    saveLocalCache,
    restoreCache,
    persistCacheWhenIdle,
    persistCacheNow,
    clearLocalCache,
  }
}
