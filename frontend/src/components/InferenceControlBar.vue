<script setup lang="ts">
import { computed } from 'vue'
import { VideoPause, Delete } from '@element-plus/icons-vue'
import type { InferenceProgressState } from '@/types/tts'

const props = defineProps<{
  progress: InferenceProgressState
  runtimeError: string | null
  cacheError: string | null
  isConnected: boolean
}>()

const emit = defineEmits<{
  'force-pause': []
  cleanup: []
  'dismiss-runtime-error': []
  'dismiss-cache-error': []
}>()

const isActive = computed(() => props.progress.status !== 'idle')

const canPause = computed(() =>
  props.progress.status === 'preparing' || props.progress.status === 'inferencing',
)

const progressStatus = computed(() => {
  switch (props.progress.status) {
    case 'cancelling': return 'warning'
    case 'error': return 'exception'
    case 'completed': return 'success'
    default: return undefined
  }
})

const statusLabel = computed(() => {
  const p = props.progress
  if (p.current_segment != null && p.total_segments != null) {
    return `${p.message} (${p.current_segment}/${p.total_segments} 段)`
  }
  return p.message || p.status
})

const progressPercent = computed(() => Math.round(props.progress.progress * 100))

const hasError = computed(() => props.runtimeError != null || props.cacheError != null)
</script>

<template>
  <section v-if="isActive || hasError" class="bg-card rounded-card p-4 shadow-card space-y-3">
    <!-- 进度条区域 -->
    <div v-if="isActive">
      <div class="flex items-center justify-between mb-2">
        <span class="text-[13px] font-semibold text-foreground">推理进度</span>
        <div class="flex items-center gap-2">
          <el-button
            type="warning"
            size="small"
            :icon="VideoPause"
            :disabled="!canPause"
            @click="emit('force-pause')"
          >
            强制暂停
          </el-button>
          <el-button
            :type="progress.status === 'idle' ? undefined : 'danger'"
            size="small"
            :plain="progress.status !== 'idle'"
            :text="progress.status === 'idle'"
            :icon="Delete"
            @click="emit('cleanup')"
          >
            清理残留
          </el-button>
        </div>
      </div>
      <el-progress
        :percentage="progressPercent"
        :status="progressStatus"
        :stroke-width="8"
        class="mb-1"
      />
      <p class="text-xs text-muted-fg">{{ statusLabel }}</p>
    </div>

    <!-- 错误提示区域 -->
    <el-alert
      v-if="runtimeError"
      type="error"
      title="推理运行时异常"
      :description="runtimeError"
      closable
      @close="emit('dismiss-runtime-error')"
    />
    <el-alert
      v-if="cacheError"
      type="warning"
      title="缓存同步异常"
      :description="cacheError"
      closable
      @close="emit('dismiss-cache-error')"
    />
  </section>
</template>
