<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ArrowDown, ArrowUp } from '@element-plus/icons-vue'
import type { InferenceParams } from '@/types/tts'
import ParameterSlider from './ParameterSlider.vue'

const props = defineProps<{ params: InferenceParams }>()

const emit = defineEmits<{
  'update:params': [value: InferenceParams]
  reset: []
}>()

const expanded = ref(true)

onMounted(() => {
  if (window.innerWidth < 768) expanded.value = false
})

function update<K extends keyof InferenceParams>(key: K, value: InferenceParams[K]) {
  emit('update:params', { ...props.params, [key]: value })
}
</script>

<template>
  <div>
    <button
      class="w-full flex items-center justify-between px-4 py-3 text-[13px] font-semibold text-foreground hover:bg-secondary/50 transition-colors"
      @click="expanded = !expanded"
    >
      推理参数
      <el-icon><component :is="expanded ? ArrowUp : ArrowDown" /></el-icon>
    </button>
    <div v-show="expanded" class="px-4 pb-4 space-y-4">
      <ParameterSlider :model-value="params.speed" label="语速" :min="0.5" :max="2.0" :step="0.05" unit="x" tooltip="语音播放速度" @update:model-value="update('speed', $event)" />
      <ParameterSlider :model-value="params.temperature" label="温度" :min="0.1" :max="2.0" :step="0.05" tooltip="控制随机性" @update:model-value="update('temperature', $event)" />
      <ParameterSlider :model-value="params.top_p" label="Top P" :min="0.0" :max="1.0" :step="0.05" tooltip="核采样概率阈值" @update:model-value="update('top_p', $event)" />
      <ParameterSlider :model-value="params.top_k" label="Top K" :min="1" :max="50" :step="1" tooltip="候选 token 数量" @update:model-value="update('top_k', $event)" />
      <ParameterSlider :model-value="params.pause_length" label="停顿时长" :min="0.0" :max="1.0" :step="0.05" unit="s" tooltip="分段间停顿秒数" @update:model-value="update('pause_length', $event)" />
      <ParameterSlider :model-value="params.chunk_length" label="分段长度" :min="10" :max="100" :step="1" tooltip="文本分段字符数" @update:model-value="update('chunk_length', $event)" />
      <div class="flex items-center gap-2">
        <label class="text-[13px] font-semibold text-foreground whitespace-nowrap">文本语言</label>
        <el-select :model-value="params.text_lang" size="small" class="w-24" @update:model-value="update('text_lang', $event)">
          <el-option value="auto" label="自动" />
          <el-option value="zh" label="中文" />
          <el-option value="en" label="English" />
          <el-option value="ja" label="日本語" />
          <el-option value="ko" label="한국어" />
        </el-select>
      </div>
      <el-button size="small" text class="!text-muted-fg" @click="emit('reset')">恢复默认</el-button>
    </div>
  </div>
</template>
