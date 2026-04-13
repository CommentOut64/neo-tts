<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { QuestionFilled } from '@element-plus/icons-vue'

const props = defineProps<{
  modelValue: number
  label: string
  min: number
  max: number
  sliderMax?: number
  inputMin?: number
  inputMax?: number
  step: number
  unit?: string
  tooltip?: string
  hint?: string
  mixed?: boolean
  mixedLabel?: string
  fallbackValue?: number
  isDirty?: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: number]
}>()

const decimals = computed(() => {
  const s = String(props.step)
  const idx = s.indexOf('.')
  return idx === -1 ? 0 : s.length - idx - 1
})

const resolvedValue = computed(() => {
  if (props.mixed) {
    return props.fallbackValue ?? props.min
  }
  return props.modelValue
})

const sliderMax = computed(() => props.sliderMax ?? props.max)
const inputMin = computed(() => props.inputMin ?? props.min)
const inputMax = computed(() => props.inputMax ?? props.max)
const useIndependentInputRange = computed(
  () => props.inputMin !== undefined || props.inputMax !== undefined || props.sliderMax !== undefined,
)

const sliderValue = computed(() => {
  return Math.min(Math.max(resolvedValue.value, props.min), sliderMax.value)
})

const inputText = ref('')
const isEditingInput = ref(false)

watch(
  [resolvedValue, decimals],
  () => {
    if (isEditingInput.value) {
      return
    }
    inputText.value = resolvedValue.value.toFixed(decimals.value)
  },
  { immediate: true },
)

const parsedInputValue = computed(() => {
  const normalized = inputText.value.trim()
  if (normalized.length === 0) {
    return null
  }
  const parsed = Number(normalized)
  return Number.isFinite(parsed) ? parsed : null
})

const hasInputError = computed(() => {
  if (!useIndependentInputRange.value) {
    return false
  }
  if (inputText.value.trim().length === 0) {
    return false
  }
  if (parsedInputValue.value === null) {
    return true
  }
  return (
    parsedInputValue.value < inputMin.value ||
    parsedInputValue.value > inputMax.value
  )
})

function handleSliderUpdate(value: number | number[]) {
  emit('update:modelValue', Array.isArray(value) ? value[0] ?? props.min : value)
}

function handleInputNumberUpdate(value: number | null | undefined) {
  emit('update:modelValue', value ?? props.min)
}

function handleCustomInputFocus() {
  isEditingInput.value = true
}

function handleCustomInput(value: string | number) {
  const nextText = String(value)
  inputText.value = nextText

  const parsed = Number(nextText)
  if (!Number.isFinite(parsed)) {
    return
  }
  if (parsed < inputMin.value || parsed > inputMax.value) {
    return
  }

  emit('update:modelValue', parsed)
}

function handleCustomInputBlur() {
  isEditingInput.value = false
  inputText.value = resolvedValue.value.toFixed(decimals.value)
}
</script>

<template>
  <div class="space-y-1">
    <div class="flex items-center justify-between">
      <label class="text-[13px] font-semibold text-foreground flex items-center gap-1">
        {{ label }}<span v-if="isDirty" class="text-red-500 font-bold ml-0.5">*</span>
        <el-tooltip v-if="tooltip" :content="tooltip" placement="top">
          <el-icon :size="14" class="text-muted-fg cursor-help"><QuestionFilled /></el-icon>
        </el-tooltip>
      </label>
      <span class="text-xs text-muted-fg tabular-nums">
        {{ mixed ? (mixedLabel ?? '多个值') : `${resolvedValue.toFixed(decimals)}${unit ?? ''}` }}
      </span>
    </div>
    <div class="flex items-center gap-3">
      <el-slider
        :model-value="sliderValue"
        :min="min" :max="sliderMax" :step="step"
        :disabled="disabled"
        :show-tooltip="false"
        class="flex-1"
        @update:model-value="handleSliderUpdate"
      />
      <el-input
        v-if="useIndependentInputRange"
        :model-value="inputText"
        :disabled="disabled"
        size="small"
        inputmode="decimal"
        class="!w-20"
        :class="{ 'parameter-slider-input-invalid': hasInputError }"
        @focus="handleCustomInputFocus"
        @blur="handleCustomInputBlur"
        @update:model-value="handleCustomInput"
      />
      <el-input-number
        v-else
        :model-value="resolvedValue"
        :min="min" :max="max" :step="step"
        :disabled="disabled"
        :controls="false"
        size="small"
        class="!w-20"
        @update:model-value="handleInputNumberUpdate"
      />
    </div>
    <p v-if="hint" class="text-[11px] leading-4 text-muted-fg">
      {{ hint }}
    </p>
  </div>
</template>

<style scoped>
:deep(.parameter-slider-input-invalid .el-input__wrapper) {
  box-shadow: 0 0 0 1px rgba(239, 68, 68, 0.9) inset;
}

:deep(.parameter-slider-input-invalid .el-input__inner) {
  color: rgb(220 38 38);
}

html.dark :deep(.parameter-slider-input-invalid .el-input__wrapper) {
  box-shadow: 0 0 0 1px rgba(248, 113, 113, 0.92) inset;
}

html.dark :deep(.parameter-slider-input-invalid .el-input__inner) {
  color: rgb(248 113 113);
}
</style>
