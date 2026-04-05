import { ref, computed, readonly } from 'vue'

import type { Router } from 'vue-router'

const text = ref('')
const draftRevision = ref(0)
const lastSentToSessionRevision = ref<number | null>(null)

function markSentToSession(revision: number) {
  lastSentToSessionRevision.value = revision
}

function sendToWorkspace(router: Router) {
  router.push('/workspace')
}

function backfillFromSession(newText: string) {
  text.value = newText
  draftRevision.value += 1
}

function setText(newText: string) {
  if (text.value !== newText) {
    text.value = newText
    draftRevision.value += 1
  }
}

const hasUnsent = computed(() => {
  if (lastSentToSessionRevision.value === null) {
    return text.value.length > 0
  }
  return draftRevision.value !== lastSentToSessionRevision.value
})
const isEmpty = computed(() => text.value.trim().length === 0)

export function useInputDraft() {
  return {
    text: readonly(text),
    draftRevision: readonly(draftRevision),
    lastSentToSessionRevision: readonly(lastSentToSessionRevision),
    hasUnsent,
    isEmpty,
    setText,
    markSentToSession,
    sendToWorkspace,
    backfillFromSession
  }
}
