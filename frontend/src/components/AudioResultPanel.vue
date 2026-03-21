<script setup lang="ts">
import { computed, provide } from 'vue'
import { Download, Microphone, WarningFilled } from '@element-plus/icons-vue'
import type { AudioHistoryItem } from '@/types/tts'
import AudioPlayer from './AudioPlayer.vue'

// Multi-player coordination
const pauseFns = new Set<() => void>()
provide('registerAudioPlayer', (pause: () => void) => { pauseFns.add(pause) })
provide('pauseOtherPlayers', (except: () => void) => {
  pauseFns.forEach(fn => { if (fn !== except) fn() })
})

const props = defineProps<{
  history: AudioHistoryItem[]
  isInferring: boolean
}>()

const emit = defineEmits<{
  download: [item: AudioHistoryItem]
}>()

const isEmpty = computed(() => props.history.length === 0 && !props.isInferring)

function timeAgo(date: Date): string {
  const diff = Math.floor((Date.now() - date.getTime()) / 1000)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}min ago`
  return `${Math.floor(diff / 3600)}h ago`
}

function truncate(text: string, max = 60): string {
  return text.length > max ? text.slice(0, max) + '...' : text
}
</script>

<template>
  <section class="bg-card rounded-card p-4 shadow-card">
    <h3 class="text-[13px] font-semibold text-foreground mb-3">合成结果</h3>

    <!-- Empty state -->
    <div v-if="isEmpty" class="flex flex-col items-center justify-center py-12">
      <el-icon :size="48" class="text-muted-fg/30 mb-3"><Microphone /></el-icon>
      <p class="text-sm text-muted-fg/50">输入文本并点击"开始推理"</p>
      <p class="text-xs text-muted-fg/30 mt-1">生成的音频将显示在此处</p>
    </div>

    <!-- Results list -->
    <div v-else class="space-y-3">
      <div
        v-for="(item, index) in history"
        :key="item.id"
        class="rounded-btn border p-3"
        :class="index === 0 ? 'border-accent/30 bg-accent/5' : 'border-border bg-muted/20'"
      >
        <div class="flex items-center justify-between mb-2">
          <span class="text-xs font-medium" :class="index === 0 ? 'text-accent' : 'text-muted-fg'">
            {{ index === 0 ? '最新' : `#${index + 1}` }}
          </span>
          <span class="text-xs text-muted-fg">{{ timeAgo(item.createdAt) }}</span>
        </div>
        <p class="text-sm text-foreground/80 mb-2">{{ truncate(item.text) }}</p>

        <!-- Pending: wave animation -->
        <div v-if="item.status === 'pending'" class="flex items-center justify-center h-10 gap-1">
          <div v-for="i in 5" :key="i" class="audio-bar w-1 bg-accent rounded-full" />
        </div>

        <!-- Error -->
        <div v-else-if="item.status === 'error'" class="flex items-center gap-2 text-destructive text-sm">
          <el-icon><WarningFilled /></el-icon>
          {{ item.errorMessage || '推理失败' }}
        </div>

        <!-- Done: player + download -->
        <template v-else>
          <AudioPlayer :src="item.blobUrl" :compact="index > 0" />
          <div v-if="item.blobUrl" class="flex justify-end mt-2">
            <el-button size="small" text :icon="Download" @click="emit('download', item)">下载 WAV</el-button>
          </div>
        </template>
      </div>
    </div>
  </section>
</template>
