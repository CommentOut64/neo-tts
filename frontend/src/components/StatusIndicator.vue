<script setup lang="ts">
import { computed } from 'vue'
import type { ConnectionStatus } from '@/composables/useHealthCheck'

const props = defineProps<{ status: ConnectionStatus }>()

const dotClass = computed(() => ({
  'bg-accent': props.status === 'online',
  'bg-destructive': props.status === 'offline',
  'bg-warning animate-pulse': props.status === 'reconnecting',
}))

const label = computed(() => ({
  online: 'Backend Online',
  offline: 'Backend Offline',
  reconnecting: '重连中...',
}[props.status]))
</script>

<template>
  <div class="flex items-center gap-2">
    <span class="w-2 h-2 rounded-full" :class="dotClass" />
    <span class="text-xs text-muted-fg">{{ label }}</span>
  </div>
</template>
