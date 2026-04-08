<script setup lang="ts">
import { computed } from "vue";
import { NodeViewWrapper, nodeViewProps } from "@tiptap/vue-3";

import {
  formatEdgeBoundaryStrategyLabel,
  formatPauseDurationSeconds,
} from "@/components/workspace/edgeDisplay";
import {
  resolvePauseBoundaryChipClass,
  shouldHighlightPauseBoundaryAsDirty,
} from "./pauseBoundaryViewModel";

const props = defineProps(nodeViewProps);

const isCrossBlock = computed(() => Boolean(props.node.attrs.crossBlock));

const secondsLabel = computed(() => {
  return formatPauseDurationSeconds(props.node.attrs.pauseDurationSeconds);
});

const strategyLabel = computed(() => {
  return formatEdgeBoundaryStrategyLabel(props.node.attrs.boundaryStrategy);
});

const title = computed(() => {
  const prefix = isCrossBlock.value ? "跨输入稿换行停顿" : "段间停顿";
  return `${prefix} · ${strategyLabel.value}`;
});

const isDirty = computed(() => {
  const dirtyEdgeIds = (props.editor.storage.segmentDecoration?.state?.dirtyEdgeIds ??
    new Set<string>()) as Set<string>;
  return shouldHighlightPauseBoundaryAsDirty({
    edgeId:
      typeof props.node.attrs.edgeId === "string" ? props.node.attrs.edgeId : null,
    dirtyEdgeIds,
  });
});

const chipClass = computed(() => {
  return resolvePauseBoundaryChipClass({
    isCrossBlock: isCrossBlock.value,
    isDirty: isDirty.value,
  });
});

function handleClick(event: MouseEvent) {
  event.preventDefault();
  event.stopPropagation();
  props.extension.options.onActivateEdge(props.node.attrs.edgeId ?? null);
}
</script>

<template>
  <NodeViewWrapper
    as="span"
    class="mx-1 inline-flex align-middle"
    :data-edge-id="props.node.attrs.edgeId"
    :data-cross-block="isCrossBlock ? 'true' : 'false'"
    :data-edge-dirty="isDirty ? 'true' : 'false'"
  >
    <button
      type="button"
      :class="chipClass"
      :title="title"
      @click="handleClick"
    >
      <span
        v-if="isCrossBlock"
        class="text-[10px] font-semibold leading-none text-foreground"
      >
        ↵
      </span>
      <span>{{ secondsLabel }}</span>
    </button>
  </NodeViewWrapper>
</template>
