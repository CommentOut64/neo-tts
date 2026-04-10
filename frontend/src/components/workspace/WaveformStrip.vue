<script setup lang="ts">
import { computed, ref, onUnmounted } from "vue";
import { usePlayback } from "@/composables/usePlayback";
import { useTimeline } from "@/composables/useTimeline";

const { currentSample, seekToSample, playbackCursorError } = usePlayback();
const { totalSamples, segmentEntries } = useTimeline();

const containerRef = ref<HTMLElement | null>(null);
const isDragging = ref(false);
const dragPreviewSample = ref<number | null>(null);

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

const displayedSample = computed(() => {
  if (isDragging.value && dragPreviewSample.value !== null) {
    return dragPreviewSample.value;
  }
  return currentSample.value;
});

// Progress as percentage
const progressPercent = computed(() => {
  if (totalSamples.value === 0) return 0;
  return (displayedSample.value / totalSamples.value) * 100;
});

function getSampleFromMouseEvent(e: MouseEvent): number | null {
  if (playbackCursorError.value) return null;
  if (!containerRef.value || totalSamples.value === 0) return null;

  const rect = containerRef.value.getBoundingClientRect();
  let x = e.clientX - rect.left;
  x = Math.max(0, Math.min(x, rect.width));

  const ratio = x / rect.width;
  return Math.floor(ratio * totalSamples.value);
}

function updateDragPreview(e: MouseEvent) {
  const targetSample = getSampleFromMouseEvent(e);
  if (targetSample === null) return;
  dragPreviewSample.value = targetSample;
}

function onMouseDown(e: MouseEvent) {
  if (playbackCursorError.value) return;
  isDragging.value = true;
  updateDragPreview(e);
  document.addEventListener("mousemove", onMouseMove);
  document.addEventListener("mouseup", onMouseUp);
}

function onMouseMove(e: MouseEvent) {
  if (!isDragging.value) return;
  updateDragPreview(e);
}

function onMouseUp(e: MouseEvent) {
  if (!isDragging.value) return;

  updateDragPreview(e);
  const targetSample = dragPreviewSample.value;
  isDragging.value = false;
  dragPreviewSample.value = null;
  document.removeEventListener("mousemove", onMouseMove);
  document.removeEventListener("mouseup", onMouseUp);

  if (targetSample !== null) {
    seekToSample(targetSample);
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
    class="w-full h-24 bg-card border border-border dark:border-transparent rounded-card shadow-card relative overflow-hidden flex flex-col justify-center shrink-0 animate-fall"
  >
    <!-- The interactive drag area -->
    <div
      ref="containerRef"
      class="h-16 relative mx-4 overflow-hidden cursor-pointer select-none group bg-secondary/5"
      @mousedown="onMouseDown"
    >
      <!-- Segments backgrounds (Temporarily hidden) -->
      <div
        v-show="false"
        v-for="(seg, idx) in normalizedSegments"
        :key="seg.id"
        class="absolute inset-y-0 transition-colors border-l border-background/20"
        :class="idx % 2 === 0 ? 'bg-blue-500/5' : 'bg-blue-500/10'"
        :style="{ left: seg.left + '%', width: seg.width + '%' }"
      ></div>

      <!-- Fake waveform bars (Background / Unplayed) -->
      <div
        class="absolute inset-0 flex items-center justify-between px-1 gap-[2px] pointer-events-none"
      >
        <div
          v-for="(h, i) in fakeWaveform"
          :key="i"
          class="flex-1 rounded-full bg-foreground/15 transition-colors"
          :style="{ height: h + '%' }"
        ></div>
      </div>

      <!-- Fake waveform bars (Highlighted via clip-path / Played) -->
      <div
        class="absolute inset-0 flex items-center justify-between px-1 gap-[2px] pointer-events-none"
        :style="{ clipPath: `inset(0 ${100 - progressPercent}% 0 0)` }"
      >
        <div
          v-for="(h, i) in fakeWaveform"
          :key="i"
          class="flex-1 rounded-full bg-blue-500/40 transition-colors"
          :style="{ height: h + '%' }"
        ></div>
      </div>

      <!-- Scrubber Line (Progress Bar) -->
      <div
        class="absolute top-0 bottom-0 w-[2px] bg-blue-500 pointer-events-none z-20"
        :class="
          isDragging
            ? 'opacity-100 shadow-[0_0_8px_rgba(59,130,246,0.8)]'
            : 'opacity-80 group-hover:opacity-100 shadow-none group-hover:shadow-[0_0_8px_rgba(59,130,246,0.5)]'
        "
        :style="{ left: progressPercent + '%', transform: `translateX(-${progressPercent}%)` }"
      >
      </div>
    </div>
  </div>
</template>
