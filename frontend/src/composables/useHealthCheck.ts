import { ref, onMounted, onBeforeUnmount } from 'vue'
import http from '@/api/http'

export type ConnectionStatus = 'online' | 'offline' | 'reconnecting'

export function useHealthCheck(intervalMs = 15_000) {
  const status = ref<ConnectionStatus>('offline')
  let failCount = 0
  let timer: ReturnType<typeof setInterval> | null = null

  async function check() {
    try {
      await http.get('/health', { timeout: 5_000 })
      if (status.value === 'offline') {
        status.value = 'reconnecting'
        setTimeout(() => {
          if (status.value === 'reconnecting') status.value = 'online'
        }, 1_000)
      } else {
        status.value = 'online'
      }
      failCount = 0
    } catch {
      failCount++
      if (failCount >= 2) status.value = 'offline'
    }
  }

  onMounted(() => {
    check()
    timer = setInterval(check, intervalMs)
  })

  onBeforeUnmount(() => {
    if (timer) clearInterval(timer)
  })

  return { status }
}
