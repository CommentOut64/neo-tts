<script setup lang="ts">
import { computed } from 'vue'
import { VideoPlay, Loading } from '@element-plus/icons-vue'

const props = defineProps<{
  text: string
  isInferring: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:text': [value: string]
  submit: []
}>()

const canSubmit = computed(() =>
  props.text.trim().length > 0 && !props.disabled && !props.isInferring
)
</script>

<template>
  <section class="bg-card rounded-card p-4 shadow-card">
    <h3 class="text-[13px] font-semibold text-foreground mb-3">合成文本</h3>
    <el-input
      :model-value="text"
      type="textarea"
      :rows="10"
      :readonly="isInferring"
      placeholder="在此输入要合成的语音文本..."
      resize="vertical"
      @update:model-value="emit('update:text', $event)"
    />
    <div class="flex items-center justify-between mt-3">
      <span class="text-xs text-muted-fg">已输入 {{ text.length }} 字符</span>
      <el-button
        type="primary"
        :icon="isInferring ? Loading : VideoPlay"
        :loading="isInferring"
        :disabled="!canSubmit"
        class="min-w-[140px] min-h-[44px]"
        aria-label="开始语音合成推理"
        @click="emit('submit')"
      >
        {{ isInferring ? '推理中...' : '开始推理' }}
      </el-button>
    </div>
  </section>
</template>
