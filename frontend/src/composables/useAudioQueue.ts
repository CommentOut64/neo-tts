import { ref, onBeforeUnmount } from 'vue'
import type { AudioHistoryItem } from '@/types/tts'

const MAX_QUEUE_SIZE = 5

export function useAudioQueue() {
  const history = ref<AudioHistoryItem[]>([])

  function pushPending(text: string): AudioHistoryItem {
    const item: AudioHistoryItem = {
      id: `${Date.now()}`,
      text,
      blobUrl: null,
      duration: null,
      createdAt: new Date(),
      status: 'pending',
    }
    history.value.unshift(item)
    trimQueue()
    return item
  }

  function markDone(item: AudioHistoryItem, blobUrl: string, duration: number | null) {
    item.blobUrl = blobUrl
    item.duration = duration
    item.status = 'done'
  }

  function markError(item: AudioHistoryItem, message: string) {
    item.status = 'error'
    item.errorMessage = message
  }

  function trimQueue() {
    while (history.value.length > MAX_QUEUE_SIZE) {
      const removed = history.value.pop()
      if (removed?.blobUrl) URL.revokeObjectURL(removed.blobUrl)
    }
  }

  function releaseAll() {
    history.value.forEach((item) => {
      if (item.blobUrl) URL.revokeObjectURL(item.blobUrl)
    })
  }

  onBeforeUnmount(releaseAll)

  return { history, pushPending, markDone, markError }
}
