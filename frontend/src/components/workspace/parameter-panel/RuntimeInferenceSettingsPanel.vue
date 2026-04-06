<script setup lang="ts">
import { computed, ref } from "vue";

import ParameterSlider from "@/components/ParameterSlider.vue";

import { MIXED_VALUE } from "./resolveEffectiveParameters";

const props = defineProps<{
  values: {
    speed: number | typeof MIXED_VALUE | null;
    top_k: number | typeof MIXED_VALUE | null;
    top_p: number | typeof MIXED_VALUE | null;
    temperature: number | typeof MIXED_VALUE | null;
    noise_scale: number | typeof MIXED_VALUE | null;
  };
}>();

const emit = defineEmits<{
  update: [field: "speed" | "top_k" | "top_p" | "temperature" | "noise_scale", value: number];
}>();

const expanded = ref(true);

const fieldValue = computed(() => ({
  speed: typeof props.values.speed === "number" ? props.values.speed : 1,
  top_k: typeof props.values.top_k === "number" ? props.values.top_k : 15,
  top_p: typeof props.values.top_p === "number" ? props.values.top_p : 1,
  temperature:
    typeof props.values.temperature === "number" ? props.values.temperature : 1,
  noise_scale:
    typeof props.values.noise_scale === "number" ? props.values.noise_scale : 0.35,
}));

function isMixed(value: unknown): value is typeof MIXED_VALUE {
  return value === MIXED_VALUE;
}
</script>

<template>
  <section class="bg-card rounded-card overflow-hidden shadow-card">
    <button
      class="w-full flex items-center justify-between px-4 py-3 text-[13px] font-semibold text-foreground transition-colors"
      @click="expanded = !expanded"
    >
      推理参数
      <span class="text-xs text-muted-fg">{{ expanded ? "收起" : "展开" }}</span>
    </button>

    <el-collapse-transition>
      <div v-show="expanded" class="overflow-hidden">
        <div class="px-4 pb-4 pt-1 space-y-4">
          <ParameterSlider
            :model-value="fieldValue.speed"
            label="语速"
            :min="0.5"
            :max="2.0"
            :step="0.05"
            unit="x"
            tooltip="语音播放速度"
            :mixed="isMixed(values.speed)"
            @update:model-value="emit('update', 'speed', $event)"
          />
          <ParameterSlider
            :model-value="fieldValue.temperature"
            label="温度"
            :min="0.1"
            :max="2.0"
            :step="0.05"
            tooltip="控制随机性"
            :mixed="isMixed(values.temperature)"
            @update:model-value="emit('update', 'temperature', $event)"
          />
          <ParameterSlider
            :model-value="fieldValue.top_p"
            label="Top P"
            :min="0.0"
            :max="1.0"
            :step="0.05"
            tooltip="核采样概率阈值"
            :mixed="isMixed(values.top_p)"
            @update:model-value="emit('update', 'top_p', $event)"
          />
          <ParameterSlider
            :model-value="fieldValue.top_k"
            label="Top K"
            :min="1"
            :max="50"
            :step="1"
            tooltip="候选 token 数量"
            :mixed="isMixed(values.top_k)"
            @update:model-value="emit('update', 'top_k', $event)"
          />
          <ParameterSlider
            :model-value="fieldValue.noise_scale"
            label="Noise Scale"
            :min="0.1"
            :max="1.0"
            :step="0.05"
            tooltip="控制音色细节扰动"
            :mixed="isMixed(values.noise_scale)"
            @update:model-value="emit('update', 'noise_scale', $event)"
          />
        </div>
      </div>
    </el-collapse-transition>
  </section>
</template>
