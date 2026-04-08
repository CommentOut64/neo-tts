<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { usePlayback } from "@/composables/usePlayback";
import { useTimeline } from "@/composables/useTimeline";
import {
  findNextSegmentStartSample,
  findPreviousSegmentStartSample,
} from "@/utils/segmentNavigation";
import { ElIcon } from "element-plus";
import {
  VideoPlay,
  VideoPause,
  ArrowLeft,
  ArrowRight,
} from "@element-plus/icons-vue";

const { isPlaying, play, pause, currentSample, seekToSample } = usePlayback();
const { totalSamples, sampleRate, segmentEntries } = useTimeline();

const sliderPercent = ref(0);
const isDraggingSlider = ref(false);

watch(
  [currentSample, totalSamples],
  ([sample, total]) => {
    if (isDraggingSlider.value || total <= 0) {
      if (total <= 0) {
        sliderPercent.value = 0;
      }
      return;
    }
    sliderPercent.value = (sample / total) * 100;
  },
  { immediate: true },
);

function formatTime(samples: number): string {
  if (sampleRate.value <= 0) return "0:00";
  const totalSeconds = Math.floor(samples / sampleRate.value);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

const displayCurrentTime = computed(() => formatTime(currentSample.value));
const displayTotalTime = computed(() => formatTime(totalSamples.value));

function seekByPercent(percent: number) {
  if (totalSamples.value === 0) return;
  seekToSample((percent / 100) * totalSamples.value);
}

function onSliderInput(value: number | number[]) {
  if (Array.isArray(value)) return;
  isDraggingSlider.value = true;
  sliderPercent.value = value;
}

function onSliderChange(value: number | number[]) {
  if (Array.isArray(value)) return;
  sliderPercent.value = value;
  isDraggingSlider.value = false;
  seekByPercent(value);
}

function onTogglePlay() {
  if (isPlaying.value) pause();
  else play();
}

function onPrevSegment() {
  const targetSample = findPreviousSegmentStartSample(
    segmentEntries.value,
    currentSample.value,
  );
  seekToSample(targetSample);
}

function onNextSegment() {
  const targetSample = findNextSegmentStartSample(
    segmentEntries.value,
    currentSample.value,
    totalSamples.value,
  );
  seekToSample(targetSample);
}
</script>

<template>
  <div class="h-16 w-full shrink-0 bg-card border border-border dark:border-transparent rounded-card shadow-card px-4 flex items-center gap-4 animate-fall">
    <div class="flex items-center gap-3">
      <button
        class="hover-state-layer w-10 h-10 flex items-center justify-center rounded-xl bg-blue-500 text-white disabled:bg-blue-300 disabled:text-white/80 disabled:cursor-not-allowed transition-colors shadow-sm"
        @click="onPrevSegment"
        title="上一段"
        :disabled="segmentEntries.length === 0"
      >
        <el-icon><ArrowLeft /></el-icon>
      </button>
      <button
        class="hover-state-layer w-12 h-12 flex items-center justify-center rounded-xl bg-blue-500 text-white shadow-md disabled:bg-blue-300 disabled:text-white/80 disabled:cursor-not-allowed transition-colors text-2xl font-bold"
        @click="onTogglePlay"
        :disabled="totalSamples === 0"
      >
        <el-icon v-if="isPlaying"><VideoPause /></el-icon>
        <el-icon v-else class="ml-[2px]"><VideoPlay /></el-icon>
      </button>
      <button
        class="hover-state-layer w-10 h-10 flex items-center justify-center rounded-xl bg-blue-500 text-white disabled:bg-blue-300 disabled:text-white/80 disabled:cursor-not-allowed transition-colors shadow-sm"
        @click="onNextSegment"
        title="下一段"
        :disabled="segmentEntries.length === 0"
      >
        <el-icon><ArrowRight /></el-icon>
      </button>
    </div>

    <div class="flex-1 flex items-center gap-4">
      <span class="text-xs font-medium text-foreground w-12 text-right opacity-80">{{ displayCurrentTime }}</span>
      <div class="flex-1 px-2 flex items-center">
        <el-slider
          :model-value="sliderPercent"
          :show-tooltip="false"
          size="small"
          class="w-full !m-0"
          @input="onSliderInput"
          @change="onSliderChange"
        />
      </div>
      <span class="text-xs font-medium text-foreground w-12 text-left opacity-80">{{ displayTotalTime }}</span>
    </div>
  </div>
</template>
