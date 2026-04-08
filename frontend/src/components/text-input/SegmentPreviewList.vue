<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue'
import { useInputDraft } from '@/composables/useInputDraft'
import { computeSegments } from '@/utils/textSegmenter'

const draft = useInputDraft()
const segments = ref<string[]>([])

let timeoutId: number | undefined
watch(() => draft.text.value, (newText) => {
  clearTimeout(timeoutId)
  timeoutId = window.setTimeout(() => {
    segments.value = computeSegments(newText)
  }, 300)
}, { immediate: true })

onBeforeUnmount(() => {
  clearTimeout(timeoutId)
})
</script>

<template>
  <div class="flex flex-col bg-card rounded-card shadow-card p-4 overflow-hidden border border-border dark:border-transparent">
    <div class="flex items-center justify-between mb-3 shrink-0">
      <h3 class="text-[13px] font-semibold text-foreground">切分预览 (只读)</h3>
      <span class="text-xs text-muted-fg">{{ segments.length }} 段</span>
    </div>
    <div class="flex-1 min-h-0 overflow-y-auto space-y-2 pr-2 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
      <div v-if="segments.length === 0" class="text-sm text-muted-fg/60 flex items-center justify-center h-full">
        暂无正文
      </div>
      <div 
        v-for="(seg, idx) in segments" 
        :key="idx"
        class="text-[13px] text-foreground bg-muted/30 px-3 py-2.5 rounded leading-relaxed break-words border border-border/30 hover:border-border/60 transition-colors"
      >
        <span class="inline-block text-[10px] text-muted-fg/50 mr-2 select-none">{{ idx + 1 }}.</span>
        {{ seg }}
      </div>
    </div>
  </div>
</template>
