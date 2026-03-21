<script setup lang="ts">
import { ref, watch, onBeforeUnmount, inject } from 'vue'
import { VideoPlay, VideoPause } from '@element-plus/icons-vue'

const props = defineProps<{
  src: string | null
  compact?: boolean
}>()

const audioEl = ref<HTMLAudioElement | null>(null)
const isPlaying = ref(false)
const currentTime = ref(0)
const duration = ref(0)

// Multi-player coordination
const registerPlayer = inject<(pause: () => void) => void>('registerAudioPlayer', () => {})
const pauseOthers = inject<(except: () => void) => void>('pauseOtherPlayers', () => {})

function pause() {
  audioEl.value?.pause()
}

registerPlayer(pause)

function formatTime(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function togglePlay() {
  if (!audioEl.value) return
  if (isPlaying.value) {
    audioEl.value.pause()
  } else {
    pauseOthers(pause)
    audioEl.value.play()
  }
}

function onTimeUpdate() {
  if (audioEl.value) currentTime.value = audioEl.value.currentTime
}

function onLoadedMetadata() {
  if (audioEl.value) duration.value = audioEl.value.duration
}

function seek(value: number) {
  if (audioEl.value) audioEl.value.currentTime = value
}

watch(() => props.src, () => {
  isPlaying.value = false
  currentTime.value = 0
  duration.value = 0
})

onBeforeUnmount(() => {
  audioEl.value?.pause()
})
</script>

<template>
  <div role="group" aria-label="音频播放器" class="flex items-center gap-3 px-3 py-2 bg-muted/30 rounded-btn">
    <audio
      ref="audioEl"
      :src="src ?? undefined"
      @timeupdate="onTimeUpdate"
      @loadedmetadata="onLoadedMetadata"
      @play="isPlaying = true"
      @pause="isPlaying = false"
      @ended="isPlaying = false; currentTime = 0"
    />
    <button
      :class="[
        'rounded-full flex items-center justify-center transition-all duration-150',
        'hover:shadow-glow-accent hover:brightness-110 active:scale-95',
        compact ? 'w-8 h-8' : 'w-10 h-10',
        src ? 'bg-accent text-background' : 'bg-muted text-muted-fg cursor-not-allowed',
      ]"
      :disabled="!src"
      :aria-label="isPlaying ? '暂停' : '播放'"
      @click="togglePlay"
    >
      <el-icon :size="compact ? 14 : 18">
        <component :is="isPlaying ? VideoPause : VideoPlay" />
      </el-icon>
    </button>
    <div class="flex-1">
      <el-slider
        :model-value="currentTime"
        :max="duration || 1"
        :step="0.1"
        :show-tooltip="false"
        :disabled="!src"
        class="!my-0"
        @update:model-value="seek($event)"
      />
    </div>
    <span class="text-xs text-muted-fg whitespace-nowrap min-w-[80px] text-right tabular-nums">
      {{ formatTime(currentTime) }} / {{ formatTime(duration) }}
    </span>
  </div>
</template>
