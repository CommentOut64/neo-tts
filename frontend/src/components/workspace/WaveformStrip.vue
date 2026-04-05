<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from "vue";
import { usePlayback } from "@/composables/usePlayback";
import { useTimeline } from "@/composables/useTimeline";

const { isPlaying, currentSample, seekToSample } = usePlayback();
const { totalSamples, segmentEntries } = useTimeline();

const containerRef = ref<HTMLElement | null>(null);
const isDragging = ref(false);

// Generate a fake waveform path once
const fakeWaveform = computed(() => {
  const bars = [];
  const numBars = 120;
  for (let i = 0; i < numBars; i++) {
    // Generate some nice random fluctuation for fake audio
    const rawVal = Math.random() * 0.6 + 0.4; // 40% to 100% height
    const finalHeight = rawVal * 90; // max height 90%

    // Make sure we have a tiny minimum height
    bars.push(Math.max(4, finalHeight));
  }
  return bars;
});

// Progress as percentage
const progressPercent = computed(() => {
  if (totalSamples.value === 0) return 0;
  return (currentSample.value / totalSamples.value) * 100;
});

function handleMouseEvent(e: MouseEvent) {
  if (!containerRef.value || totalSamples.value === 0) return;

  const rect = containerRef.value.getBoundingClientRect();
  let x = e.clientX - rect.left;
  x = Math.max(0, Math.min(x, rect.width));

  const ratio = x / rect.width;
  const targetSample = Math.floor(ratio * totalSamples.value);
  seekToSample(targetSample);
}

function onMouseDown(e: MouseEvent) {
  isDragging.value = true;
  handleMouseEvent(e);
  document.addEventListener("mousemove", onMouseMove);
  document.addEventListener("mouseup", onMouseUp);
}

function onMouseMove(e: MouseEvent) {
  if (!isDragging.value) return;
  handleMouseEvent(e);
}

function onMouseUp(e: MouseEvent) {
  if (isDragging.value) {
    handleMouseEvent(e);
    isDragging.value = false;
    document.removeEventListener("mousemove", onMouseMove);
    document.removeEventListener("mouseup", onMouseUp);
  }
}

onUnmounted(() => {
  document.removeEventListener("mousemove", onMouseMove);
  document.removeEventListener("mouseup", onMouseUp);
});

// Compute positions for segments to show them on the waveform
const normalizedSegments = computed(() => {
  if (totalSamples.value === 0) return [];
  return segmentEntries.value.map((seg) => {
    return {
      id: seg.segment_id,
      left: (seg.start_sample / totalSamples.value) * 100,
      width: ((seg.end_sample - seg.start_sample) / totalSamples.value) * 100,
    };
  });
});
</script>

<template>
  <div
    class="w-full h-28 bg-card border-none rounded-card shadow-card relative overflow-hidden flex flex-col justify-between shrink-0"
  >
    <div
      class="px-4 py-2 flex items-center justify-between text-xs font-semibold text-muted-fg uppercase tracking-wider z-10 shrink-0"
    >
      <span>全局波形预览 (Placeholder)</span>
      <span class="opacity-50">Drag to Seek</span>
    </div>

    <!-- The interactive drag area -->
    <div
      ref="containerRef"
      class="flex-1 relative mx-4 mb-3 rounded-lg overflow-hidden cursor-pointer select-none group bg-secondary/10"
      @mousedown="onMouseDown"
    >
      <!-- Segments backgrounds -->
      <div
        v-for="(seg, idx) in normalizedSegments"
        :key="seg.id"
        class="absolute inset-y-0 transition-colors border-l border-background/20"
        :class="idx % 2 === 0 ? 'bg-blue-500/5' : 'bg-blue-500/10'"
        :style="{ left: seg.left + '%', width: seg.width + '%' }"
      ></div>

      <!-- Fake waveform bars (Background) -->
      <div
        class="absolute inset-0 flex items-center justify-between px-1 gap-[2px] opacity-30 pointer-events-none"
      >
        <div
          v-for="(h, i) in fakeWaveform"
          :key="i"
          class="flex-1 bg-foreground rounded-full"
          :style="{ height: h + '%' }"
        ></div>
      </div>

      <!-- Fake waveform bars (Highlighted via clip-path) -->
      <div
        class="absolute inset-0 flex items-center justify-between px-1 gap-[2px] pointer-events-none"
        :style="{ clipPath: `inset(0 ${100 - progressPercent}% 0 0)` }"
      >
        <div
          v-for="(h, i) in fakeWaveform"
          :key="i"
          class="flex-1 bg-blue-500 rounded-full shadow-[0_0_8px_rgba(59,130,246,0.5)]"
          :style="{ height: h + '%' }"
        ></div>
      </div>

      <!-- Scrubber Line -->
      <div
        class="absolute top-0 bottom-0 w-[2px] bg-blue-500 pointer-events-none z-20 transition-opacity"
        :class="
          isDragging
            ? 'opacity-100 shadow-[0_0_8px_rgba(59,130,246,0.8)]'
            : 'opacity-80 group-hover:opacity-100'
        "
        :style="{ left: progressPercent + '%' }"
      >
        <div
          class="absolute -top-1 -translate-x-[calc(50%-1px)] w-3 h-3 rounded-full bg-blue-500 shadow-sm"
        />
      </div>
    </div>
  </div>
</template>
