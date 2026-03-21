<script setup lang="ts">
import { computed } from 'vue'
import { QuestionFilled } from '@element-plus/icons-vue'

const props = defineProps<{
  modelValue: number
  label: string
  min: number
  max: number
  step: number
  unit?: string
  tooltip?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: number]
}>()

const decimals = computed(() => {
  const s = String(props.step)
  const idx = s.indexOf('.')
  return idx === -1 ? 0 : s.length - idx - 1
})
</script>

<template>
  <div class="space-y-1">
    <div class="flex items-center justify-between">
      <label class="text-[13px] font-semibold text-foreground flex items-center gap-1">
        {{ label }}
        <el-tooltip v-if="tooltip" :content="tooltip" placement="top">
          <el-icon :size="14" class="text-muted-fg cursor-help"><QuestionFilled /></el-icon>
        </el-tooltip>
      </label>
      <span class="text-xs text-muted-fg tabular-nums">
        {{ modelValue.toFixed(decimals) }}{{ unit }}
      </span>
    </div>
    <div class="flex items-center gap-3">
      <el-slider
        :model-value="modelValue"
        :min="min" :max="max" :step="step"
        :show-tooltip="false"
        class="flex-1"
        @update:model-value="emit('update:modelValue', $event)"
      />
      <el-input-number
        :model-value="modelValue"
        :min="min" :max="max" :step="step"
        :controls="false"
        size="small"
        class="!w-20"
        @update:model-value="emit('update:modelValue', $event ?? min)"
      />
    </div>
  </div>
</template>
