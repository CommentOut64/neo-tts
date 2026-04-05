<script setup lang="ts">
import { computed } from "vue";
import { useTimeline } from "@/composables/useTimeline";
import { usePlayback } from "@/composables/usePlayback";
import { useEditSession } from "@/composables/useEditSession";

const { segmentEntries } = useTimeline();
const { currentSegmentId, play, seekToSegment } = usePlayback();
const { segments, segmentsLoaded } = useEditSession();

const segmentTexts = computed(() => {
  const map = new Map<string, string>();
  for (const segment of segments.value) {
    if (segment.raw_text) {
      map.set(segment.segment_id, segment.raw_text);
    }
  }
  return map;
});

const displaySegments = computed(() => {
  return segmentEntries.value.map((segment) => {
    const displayText = segmentTexts.value.get(segment.segment_id) ||
      (segmentsLoaded.value
        ? `[ 段落内容缺失 / ${segment.segment_id} ]`
        : `[ 段落内容加载中 / ${segment.segment_id} ]`);

    return {
      ...segment,
      displayText,
    };
  });
});

function isCurrentSegment(segmentId: string) {
  return currentSegmentId.value === segmentId;
}

function onSegmentClick(segmentId: string) {
  seekToSegment(segmentId);
  play();
}
</script>

<template>
  <div
    class="flex-1 w-full bg-card rounded-card shadow-card border border-border p-4 overflow-y-auto scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent"
  >
    <div class="text-sm font-semibold mb-4 text-muted-fg">时间线片段</div>
    <div class="flex flex-col gap-2">
      <div
        v-for="seg in displaySegments"
        :key="seg.segment_id"
        class="p-3 rounded-lg border transition-colors cursor-pointer"
        :class="{
          'bg-accent/10 border-accent text-accent-fg':
            isCurrentSegment(seg.segment_id),
          'bg-background border-border text-foreground hover:border-accent/50':
            !isCurrentSegment(seg.segment_id),
        }"
        @click="onSegmentClick(seg.segment_id)"
      >
        <span class="text-base break-words">
          {{ seg.displayText }}
        </span>
      </div>
      <div
        v-if="displaySegments.length === 0"
        class="text-muted-fg text-center py-4"
      >
        暂无可用分段
      </div>
    </div>
  </div>
</template>
