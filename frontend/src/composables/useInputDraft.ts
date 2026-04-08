import { ref, computed } from 'vue'
import type { Router } from 'vue-router'

const STORAGE_KEY = 'neo-tts-input-draft'

interface InputDraftEnvelope {
  text: string
  draftRevision: number
  lastSentToSessionRevision: number | null
}

const text = ref<string>('')
const draftRevision = ref<number>(0)
const lastSentToSessionRevision = ref<number | null>(null)
let hydrated = false

function hasBrowserStorage(): boolean {
  return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined'
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
  } catch {
    window.localStorage.removeItem(STORAGE_KEY)
  }
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
    text.value = t
    draftRevision.value++
    persistDraftState()
  }

  function setText(newText: string) {
    text.value = newText
    draftRevision.value++
    persistDraftState()
  }

  return {
    text,
    draftRevision,
    lastSentToSessionRevision,
    hasUnsent,
    isEmpty,
    sendToWorkspace,
    markSentToSession,
    backfillFromSession,
    setText
  }
}
