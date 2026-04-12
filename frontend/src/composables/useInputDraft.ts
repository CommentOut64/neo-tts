import { ref, computed } from 'vue'
import type { Router } from 'vue-router'

const STORAGE_KEY = 'neo-tts-input-draft'

export type InputDraftSource = 'manual' | 'applied_text' | 'input_handoff'
export type InputTextLanguage = 'auto' | 'zh' | 'en' | 'ja' | 'ko'

interface InputDraftEnvelope {
  text: string
  draftRevision: number
  lastSentToSessionRevision: number | null
  source: InputDraftSource
  lastSessionInitialText: string | null
  textLanguage: InputTextLanguage
}

const text = ref<string>('')
const draftRevision = ref<number>(0)
const lastSentToSessionRevision = ref<number | null>(null)
const source = ref<InputDraftSource>('manual')
const lastSessionInitialText = ref<string | null>(null)
const textLanguage = ref<InputTextLanguage>('auto')
let hydrated = false

function hasBrowserStorage(): boolean {
  return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined'
}

function normalizeSource(
  raw: unknown,
  normalizedRevision: number,
  normalizedLastSent: number | null,
): InputDraftSource {
  if (raw === 'manual' || raw === 'applied_text' || raw === 'input_handoff') {
    return raw
  }

  // 兼容旧持久化来源命名。
  if (raw === 'session') {
    return 'applied_text'
  }

  if (raw === 'workspace') {
    return 'input_handoff'
  }

  if (normalizedRevision > 0 && normalizedLastSent === normalizedRevision) {
    return 'applied_text'
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
    lastSessionInitialText:
      typeof candidate.lastSessionInitialText === 'string' && candidate.lastSessionInitialText.length > 0
        ? candidate.lastSessionInitialText
        : null,
    textLanguage:
      candidate.textLanguage === 'zh' ||
      candidate.textLanguage === 'en' ||
      candidate.textLanguage === 'ja' ||
      candidate.textLanguage === 'ko'
        ? candidate.textLanguage
        : 'auto',
  }
}

function persistDraftState() {
  if (!hasBrowserStorage()) return

  if (text.value.length === 0 && !lastSessionInitialText.value && textLanguage.value === 'auto') {
    window.localStorage.removeItem(STORAGE_KEY)
    return
  }

  const envelope: InputDraftEnvelope = {
    text: text.value,
    draftRevision: draftRevision.value,
    lastSentToSessionRevision: lastSentToSessionRevision.value,
    source: source.value,
    lastSessionInitialText: lastSessionInitialText.value,
    textLanguage: textLanguage.value,
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
    lastSessionInitialText.value = envelope.lastSessionInitialText
    textLanguage.value = envelope.textLanguage
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

  function backfillFromAppliedText(t: string) {
    return applyIncomingText(t, 'applied_text')
  }

  function handoffFromWorkspace(t: string) {
    return applyIncomingText(t, 'input_handoff')
  }

  function rememberLastSessionInitialText(nextText: string) {
    lastSessionInitialText.value = nextText.trim().length > 0 ? nextText : null
    persistDraftState()
  }

  function restoreLastSessionInitialText() {
    if (!lastSessionInitialText.value) {
      return false
    }

    setText(lastSessionInitialText.value)
    return true
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

  function setTextLanguage(nextTextLanguage: InputTextLanguage) {
    if (textLanguage.value === nextTextLanguage) {
      return
    }
    textLanguage.value = nextTextLanguage
    persistDraftState()
  }

  return {
    text,
    textLanguage,
    draftRevision,
    lastSentToSessionRevision,
    source,
    lastSessionInitialText,
    hasUnsent,
    isEmpty,
    sendToWorkspace,
    markSentToSession,
    backfillFromAppliedText,
    handoffFromWorkspace,
    rememberLastSessionInitialText,
    restoreLastSessionInitialText,
    setText,
    setTextLanguage,
  }
}
