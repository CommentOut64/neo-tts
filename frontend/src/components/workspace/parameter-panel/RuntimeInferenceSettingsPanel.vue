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
  dirtyFields?: Set<string>;
  status: "ready" | "resolving" | "unresolved";
  disabled?: boolean;
}>();

const emit = defineEmits<{
  update: [field: "speed" | "top_k" | "top_p" | "temperature" | "noise_scale", value: number];
}>();

const expanded = ref(true);

const statusMessage = computed(() => {
  if (props.status === "resolving") {
    return "正在同步最新正式参数，稍后会恢复可编辑状态。";
  }
  if (props.status === "unresolved") {
    return "当前正式参数暂不可解析，请重试或重新选择范围。";
  }
  return null;
});

const canRenderControls = computed(() =>
  [
    props.values.speed,
    props.values.top_k,
    props.values.top_p,
    props.values.temperature,
    props.values.noise_scale,
  ].some((value) => typeof value === "number" || isMixed(value)),
);

const fieldValue = computed(() => ({
  speed: typeof props.values.speed === "number" ? props.values.speed : null,
  top_k: typeof props.values.top_k === "number" ? props.values.top_k : null,
  top_p: typeof props.values.top_p === "number" ? props.values.top_p : null,
  temperature:
    typeof props.values.temperature === "number" ? props.values.temperature : null,
  noise_scale:
    typeof props.values.noise_scale === "number" ? props.values.noise_scale : null,
}));

function isMixed(value: unknown): value is typeof MIXED_VALUE {
  return value === MIXED_VALUE;
}
</script>

<template>
  <section class="bg-card rounded-card overflow-hidden shadow-card border border-border dark:border-transparent animate-fall">
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
          <div
            v-if="statusMessage"
            class="rounded-card border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-muted-fg"
          >
            {{ statusMessage }}
          </div>
          <template v-if="canRenderControls">
          <ParameterSlider
            :model-value="fieldValue.speed ?? 1"
            label="语速"
            :min="0.5"
            :max="2.0"
            :step="0.05"
            unit="x"
            tooltip="语音播放速度"
            :mixed="isMixed(values.speed)"
            :is-dirty="dirtyFields?.has('renderProfile.speed')"
            :disabled="disabled || status !== 'ready'"
            @update:model-value="emit('update', 'speed', $event)"
          />
          <ParameterSlider
            :model-value="fieldValue.temperature ?? 1"
            label="温度"
            :min="0.1"
            :max="2.0"
            :step="0.05"
            tooltip="控制随机性"
            :mixed="isMixed(values.temperature)"
            :is-dirty="dirtyFields?.has('renderProfile.temperature')"
            :disabled="disabled || status !== 'ready'"
            @update:model-value="emit('update', 'temperature', $event)"
          />
          <ParameterSlider
            :model-value="fieldValue.top_p ?? 1"
            label="Top P"
            :min="0.0"
            :max="1.0"
            :step="0.05"
            tooltip="核采样概率阈值"
            :mixed="isMixed(values.top_p)"
            :is-dirty="dirtyFields?.has('renderProfile.top_p')"
            :disabled="disabled || status !== 'ready'"
            @update:model-value="emit('update', 'top_p', $event)"
          />
          <ParameterSlider
            :model-value="fieldValue.top_k ?? 15"
            label="Top K"
            :min="1"
            :max="50"
            :step="1"
            tooltip="候选 token 数量"
            :mixed="isMixed(values.top_k)"
            :is-dirty="dirtyFields?.has('renderProfile.top_k')"
            :disabled="disabled || status !== 'ready'"
            @update:model-value="emit('update', 'top_k', $event)"
          />
          <ParameterSlider
            :model-value="fieldValue.noise_scale ?? 0.35"
            label="Noise Scale"
            :min="0.1"
            :max="1.0"
            :step="0.05"
            tooltip="控制音色细节扰动"
            :mixed="isMixed(values.noise_scale)"
            :is-dirty="dirtyFields?.has('renderProfile.noise_scale')"
            :disabled="disabled || status !== 'ready'"
            @update:model-value="emit('update', 'noise_scale', $event)"
          />
          </template>
        </div>
      </div>
    </el-collapse-transition>
  </section>
</template>
