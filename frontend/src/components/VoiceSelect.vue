<script setup lang="ts">
import type { VoiceProfile } from '@/types/tts'

defineProps<{
  modelValue: string
  voices: VoiceProfile[]
  placeholder?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()
</script>

<template>
  <el-select
    :model-value="modelValue"
    :placeholder="placeholder ?? '选择模型'"
    size="default"
    class="!w-min"
    style="min-width: 280px;"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-option
      v-for="v in voices"
      :key="v.name"
      :value="v.name"
      :label="`${v.name} — ${v.description}`"
    />
  </el-select>
</template>
