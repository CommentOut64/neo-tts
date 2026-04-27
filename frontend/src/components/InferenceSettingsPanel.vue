<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ArrowDown, ArrowUp } from '@element-plus/icons-vue'
import type { InferenceParams } from '@/types/tts'
import ParameterSlider from './ParameterSlider.vue'

type InferenceSettingsPanelParams = Omit<
  InferenceParams,
  'chunk_length' | 'text_split_method'
> &
  Partial<Pick<InferenceParams, 'chunk_length' | 'text_split_method'>>

const props = withDefaults(
  defineProps<{
    params: InferenceSettingsPanelParams
    showTextSplitMethod?: boolean
    showNoiseScale?: boolean
    showChunkLength?: boolean
  }>(),
  {
    showTextSplitMethod: true,
    showNoiseScale: false,
    showChunkLength: true,
  },
)

const emit = defineEmits<{
  'update:params': [value: InferenceSettingsPanelParams]
  reset: []
}>()

const expanded = ref(true)

onMounted(() => {
  if (window.innerWidth < 768) expanded.value = false
})

function update<K extends keyof InferenceSettingsPanelParams>(
  key: K,
  value: InferenceSettingsPanelParams[K],
) {
  emit('update:params', { ...props.params, [key]: value })
}
</script>

<template>
  <div>
    <button
      class="w-full flex items-center justify-between px-4 py-3 text-[13px] font-semibold text-foreground transition-colors"
      @click="expanded = !expanded"
    >
      推理参数
      <el-icon><component :is="expanded ? ArrowUp : ArrowDown" /></el-icon>
    </button>
    <el-collapse-transition>
      <div v-show="expanded" class="overflow-hidden">
        <div class="px-4 pb-4 pt-1 space-y-4">
          <ParameterSlider :model-value="params.speed" label="语速" :min="0.5" :max="2.0" :step="0.05" unit="x" tooltip="语音播放速度" @update:model-value="update('speed', $event)" />
          <ParameterSlider :model-value="params.temperature" label="温度" :min="0.1" :max="2.0" :step="0.05" tooltip="控制随机性" @update:model-value="update('temperature', $event)" />
          <ParameterSlider :model-value="params.top_p" label="Top P" :min="0.0" :max="1.0" :step="0.05" tooltip="核采样概率阈值" @update:model-value="update('top_p', $event)" />
          <ParameterSlider :model-value="params.top_k" label="Top K" :min="1" :max="50" :step="1" tooltip="候选 token 数量" @update:model-value="update('top_k', $event)" />
          <ParameterSlider v-if="props.showNoiseScale" :model-value="params.noise_scale ?? 0.35" label="Noise Scale" :min="0.1" :max="1.0" :step="0.05" tooltip="控制 SoVITS 解码噪声" @update:model-value="update('noise_scale', $event)" />
          <ParameterSlider :model-value="params.pause_length" label="停顿时长" :min="0.0" :max="1.0" :step="0.05" unit="s" tooltip="分段间停顿秒数" @update:model-value="update('pause_length', $event)" />
          <ParameterSlider v-if="props.showChunkLength" :model-value="params.chunk_length" label="分段长度" :min="10" :max="100" :step="1" tooltip="文本分段字符数" @update:model-value="update('chunk_length', $event)" />
          <div class="flex flex-col gap-3">
            <label class="text-[13px] font-semibold text-foreground">文本语言</label>
            <el-select :model-value="params.text_lang" size="small" class="!w-min" style="min-width: 90px;" @update:model-value="update('text_lang', $event)">
              <el-option value="auto" label="自动" />
              <el-option value="zh" label="中文" />
              <el-option value="en" label="英文" />
              <el-option value="ja" label="日文" />
              <el-option value="ko" label="韩文" />
            </el-select>
          </div>
          <div v-if="props.showTextSplitMethod" class="flex flex-col gap-3">
            <label class="text-[13px] font-semibold text-foreground">切分策略</label>
            <el-select :model-value="params.text_split_method" size="small" class="!w-min" style="min-width: 140px;" @update:model-value="update('text_split_method', $event)">
              <el-option value="cut0" label="不切分 (cut0)" />
              <el-option value="cut1" label="四句一切 (cut1)" />
              <el-option value="cut2" label="50字一切 (cut2)" />
              <el-option value="cut3" label="按中文句号 (cut3)" />
              <el-option value="cut4" label="按英文句号 (cut4)" />
              <el-option value="cut5" label="按标点切分 (cut5)" />
            </el-select>
          </div>
          <div class="pt-2">
            <el-button size="small" text class="!px-0 !text-muted-fg" @click="emit('reset')">恢复默认</el-button>
          </div>
        </div>
      </div>
    </el-collapse-transition>
  </div>
</template>
