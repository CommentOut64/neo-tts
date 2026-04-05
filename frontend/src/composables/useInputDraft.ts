import { ref, computed } from 'vue'

const text = ref<string>('')
const draftRevision = ref<number>(0)
const lastSentToSessionRevision = ref<number | null>(null)

export function useInputDraft() {
  const hasUnsent = computed(() => draftRevision.value !== lastSentToSessionRevision.value)
  const isEmpty = computed(() => text.value.trim().length === 0)

  function sendToWorkspace() {
    // router setup
  }

  function markSentToSession(rev: number) {
    lastSentToSessionRevision.value = rev
  }

  function backfillFromSession(t: string) {
    text.value = t
    draftRevision.value++
  }

  function setText(newText: string) {
    text.value = newText
    draftRevision.value++
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
