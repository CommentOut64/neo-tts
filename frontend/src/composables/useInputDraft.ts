import { ref, computed } from 'vue'
import type { Router } from 'vue-router'

const STORAGE_KEY = 'neo-tts-input-draft'

export type InputDraftSource = 'manual' | 'session' | 'workspace'

interface InputDraftEnvelope {
  text: string
  draftRevision: number
  lastSentToSessionRevision: number | null
  source: InputDraftSource
}

const text = ref<string>('')
const draftRevision = ref<number>(0)
const lastSentToSessionRevision = ref<number | null>(null)
const source = ref<InputDraftSource>('manual')
let hydrated = false

function hasBrowserStorage(): boolean {
  return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined'
}

function normalizeSource(
  raw: unknown,
  normalizedRevision: number,
  normalizedLastSent: number | null,
): InputDraftSource {
  if (raw === 'manual' || raw === 'session' || raw === 'workspace') {
    return raw
  }

  if (normalizedRevision > 0 && normalizedLastSent === normalizedRevision) {
    return 'session'
  }

  return 'manual'
}

function normalizeEnvelope(raw: unknown): InputDraftEnvelope | null {
  if (!raw || typeof raw !== 'object') {
    return null
  }

  const candidate = raw as Record<string, unknown>
  if (typeof candidate.text !== 'string') {
    return null
  }

  const normalizedRevision = typeof candidate.draftRevision === 'number' && Number.isFinite(candidate.draftRevision)
    ? candidate.draftRevision
    : 0

  const normalizedLastSent = typeof candidate.lastSentToSessionRevision === 'number' && Number.isFinite(candidate.lastSentToSessionRevision)
    ? candidate.lastSentToSessionRevision
    : null

  return {
    text: candidate.text,
    draftRevision: normalizedRevision,
    lastSentToSessionRevision: normalizedLastSent,
    source: normalizeSource(candidate.source, normalizedRevision, normalizedLastSent),
  }
}

function persistDraftState() {
  if (!hasBrowserStorage()) return

  if (text.value.length === 0) {
    window.localStorage.removeItem(STORAGE_KEY)
    return
  }

  const envelope: InputDraftEnvelope = {
    text: text.value,
    draftRevision: draftRevision.value,
    lastSentToSessionRevision: lastSentToSessionRevision.value,
    source: source.value,
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(envelope))
}

function hydrateDraftState() {
  if (hydrated || !hasBrowserStorage()) return
  hydrated = true

  const raw = window.localStorage.getItem(STORAGE_KEY)
  if (!raw) return

  try {
    const envelope = normalizeEnvelope(JSON.parse(raw))
    if (!envelope) {
      window.localStorage.removeItem(STORAGE_KEY)
      return
    }

    text.value = envelope.text
    draftRevision.value = envelope.draftRevision
    lastSentToSessionRevision.value = envelope.lastSentToSessionRevision
    source.value = envelope.source
  } catch {
    window.localStorage.removeItem(STORAGE_KEY)
  }
}

function applyIncomingText(
  newText: string,
  nextSource: Exclude<InputDraftSource, 'manual'>,
): boolean {
  const hasChanged = text.value !== newText
  text.value = newText
  source.value = nextSource
  if (hasChanged) {
    draftRevision.value++
  }
  persistDraftState()
  return true
}

export function useInputDraft() {
  hydrateDraftState()

  const hasUnsent = computed(() => draftRevision.value !== lastSentToSessionRevision.value)
  const isEmpty = computed(() => text.value.trim().length === 0)

  function sendToWorkspace(router: Router) {
    return router.push('/workspace')
  }

  function markSentToSession(rev: number) {
    lastSentToSessionRevision.value = rev
    persistDraftState()
  }

  function backfillFromSession(t: string) {
    return applyIncomingText(t, 'session')
  }

  function syncFromWorkspaceDraft(t: string) {
    if (source.value === 'manual' && text.value.trim().length > 0 && text.value !== t) {
      return false
    }

    if (text.value === t) {
      if (source.value === 'workspace') {
        persistDraftState()
        return true
      }

      if (source.value === 'manual') {
        persistDraftState()
        return false
      }

      persistDraftState()
      return true
    }

    return applyIncomingText(t, 'workspace')
  }

  function setText(newText: string) {
    const hasChanged = text.value !== newText
    text.value = newText
    source.value = 'manual'
    if (hasChanged) {
      draftRevision.value++
    }
    persistDraftState()
  }

  return {
    text,
    draftRevision,
    lastSentToSessionRevision,
    source,
    hasUnsent,
    isEmpty,
    sendToWorkspace,
    markSentToSession,
    backfillFromSession,
    syncFromWorkspaceDraft,
    setText
  }
}
