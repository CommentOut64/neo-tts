<script setup lang="ts">
import { computed } from 'vue'

import type { StandardizationPreviewSegment } from '@/types/editSession'
import { buildStandardizationPreviewDisplayText } from '@/utils/standardizationPreviewDisplay'

const props = defineProps<{
  text: string
  segments: StandardizationPreviewSegment[]
  totalSegments: number
  isLoading: boolean
  isLoadingMore: boolean
  errorMessage: string
  analysisStage: 'light' | 'complete'
  hasMore: boolean
  loadMore: () => Promise<void> | void
}>()

const displaySegments = computed(() =>
  (props.segments || []).map((segment) => ({
    ...segment,
    displayText: buildStandardizationPreviewDisplayText(segment),
  })),
)
</script>

<template>
  <div class="flex flex-col bg-card rounded-card shadow-card p-4 overflow-hidden border border-border dark:border-transparent animate-fall">
    <div class="flex items-center justify-between mb-3 shrink-0">
      <div class="flex items-center gap-2">
        <h3 class="text-[13px] font-semibold text-foreground">切分预览 (只读)</h3>
        <span
          v-if="analysisStage === 'light' && text?.trim()"
          class="text-[10px] px-2 py-0.5 rounded-full bg-warning/10 text-warning"
        >
          快速分析
        </span>
      </div>
      <span class="text-xs text-muted-fg">{{ totalSegments }} 段</span>
    </div>
    <div class="flex-1 min-h-0 overflow-y-auto space-y-2 pr-2 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
      <div v-if="!text?.trim()" class="text-sm text-muted-fg/60 flex items-center justify-center h-full">
        暂无正文
      </div>
      <div v-else-if="isLoading" class="text-sm text-muted-fg/60 flex items-center justify-center h-full">
        分析中
      </div>
      <div v-else-if="errorMessage && displaySegments.length === 0" class="text-sm text-danger flex items-center justify-center h-full">
        {{ errorMessage }}
      </div>
      <div
        v-else-if="analysisStage === 'light'"
        class="text-xs text-muted-fg bg-muted/20 border border-border/30 rounded px-3 py-2"
      >
        长文本预览已切到快速分析，只返回前几段供检查；可继续加载更多分段。
      </div>
      <div 
        v-for="seg in displaySegments" 
        :key="seg.order_key"
        class="text-[13px] text-foreground bg-muted/30 px-3 py-2.5 rounded leading-relaxed break-words border border-border/30 hover:border-border/60 transition-colors"
      >
        <span class="inline-block text-[10px] text-muted-fg/50 mr-2 select-none">{{ seg.order_key }}.</span>
        {{ seg.displayText }}
      </div>
      <div v-if="errorMessage && displaySegments.length > 0" class="text-xs text-danger px-1">
        {{ errorMessage }}
      </div>
      <div v-if="hasMore" class="flex items-center justify-center pt-2">
        <el-button
          size="small"
          plain
          :loading="isLoadingMore"
          @click="loadMore"
        >
          加载更多
        </el-button>
      </div>
    </div>
  </div>
</template>

