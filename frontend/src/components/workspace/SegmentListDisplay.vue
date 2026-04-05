<script setup lang="ts">
import { computed, ref } from "vue";
import { useTimeline } from "@/composables/useTimeline";
import { usePlayback } from "@/composables/usePlayback";
import { useEditSession } from "@/composables/useEditSession";
import { useSegmentSelection } from "@/composables/useSegmentSelection";
import { useWorkspaceLightEdit } from "@/composables/useWorkspaceLightEdit";
import DirtySegmentBadge from "./DirtySegmentBadge.vue";
import WorkspaceEditorHost from "./WorkspaceEditorHost.vue";

const { segmentEntries } = useTimeline();
const { currentSegmentId, play, seekToSegment } = usePlayback();
const { segments, segmentsLoaded } = useEditSession();
const segmentSelection = useSegmentSelection();
const lightEdit = useWorkspaceLightEdit();

const editingSegmentId = ref<string | null>(null);

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
    // Show draft if dirty, else original raw_text
    const isDirty = lightEdit.isDirty(segment.segment_id);
    const draftText = lightEdit.getDraft(segment.segment_id);
    
    let displayText = '';
    if (isDirty && draftText !== undefined) {
      displayText = draftText;
    } else {
      displayText = segmentTexts.value.get(segment.segment_id) ||
        (segmentsLoaded.value
          ? `[ 段落内容缺失 / ${segment.segment_id} ]`
          : `[ 段落内容加载中 / ${segment.segment_id} ]`);
    }

    return {
      ...segment,
      displayText,
      isDirty,
    };
  });
});

function isCurrentSegment(segmentId: string) {
  return currentSegmentId.value === segmentId;
}

function isSelected(segmentId: string) {
  return segmentSelection.isSelected(segmentId);
}

function onSegmentClick(event: MouseEvent, segmentId: string) {
  if (editingSegmentId.value) return; // Prevent selection changes while editing

  const allIds = segmentEntries.value.map(s => s.segment_id);
  
  if (event.shiftKey) {
    segmentSelection.rangeSelect(segmentId, allIds);
  } else if (event.ctrlKey || event.metaKey) {
    segmentSelection.toggleSelect(segmentId);
  } else {
    segmentSelection.select(segmentId);
  }

  // Also trigger playback jump
  seekToSegment(segmentId);
  play();
}

function onSegmentDoubleClick(segmentId: string) {
  editingSegmentId.value = segmentId;
}
</script>

<template>
  <div
    class="flex-1 w-full bg-card rounded-card shadow-card border border-border p-4 overflow-y-auto scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent"
    @click.self="segmentSelection.clearSelection()"
  >
    <div class="text-sm font-semibold mb-4 text-muted-fg">时间线片段</div>      
    <div class="flex flex-col gap-2">
      <div
        v-for="seg in displaySegments"
        :key="seg.segment_id"
      >
        <!-- Editor Mode -->
        <WorkspaceEditorHost
          v-if="editingSegmentId === seg.segment_id"
          :segment-id="seg.segment_id"
          :initial-text="seg.displayText"
          @exit-edit="editingSegmentId = null"
        />

        <!-- Display Mode -->
        <div
          v-else
          class="p-3 rounded-lg border transition-colors cursor-pointer select-none"
          :class="{
            'bg-accent/10 border-accent text-accent-fg': isCurrentSegment(seg.segment_id),
            'bg-blue-500/20 border-blue-500 text-foreground': !isCurrentSegment(seg.segment_id) && isSelected(seg.segment_id),
            'bg-background border-border text-foreground hover:border-accent/50': 
              !isCurrentSegment(seg.segment_id) && !isSelected(seg.segment_id),
          }"
          @click="onSegmentClick($event, seg.segment_id)"
          @dblclick="onSegmentDoubleClick(seg.segment_id)"
        >
          <span class="text-base break-words">
            {{ seg.displayText }}
          </span>
          <DirtySegmentBadge :is-dirty="seg.isDirty" />
        </div>
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
