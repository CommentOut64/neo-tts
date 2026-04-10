<script setup lang="ts">
import { computed } from "vue";
import {
  NodeViewContent,
  NodeViewWrapper,
  nodeViewProps,
} from "@tiptap/vue-3";

const props = defineProps(nodeViewProps);

const segmentId = computed(() =>
  typeof props.node.attrs.segmentId === "string" ? props.node.attrs.segmentId : "",
);

const lineNumberLabel = computed(() => {
  const orderedSegmentIds = props.editor.storage.segmentDecoration?.state?.renderMap
    ?.orderedSegmentIds as string[] | undefined;
  if (!orderedSegmentIds || segmentId.value.length === 0) {
    return "";
  }

  const index = orderedSegmentIds.indexOf(segmentId.value);
  return index >= 0 ? String(index + 1).padStart(2, "0") : "";
});

const showReorderHandle = computed(() => {
  return Boolean(props.editor.storage.segmentDecoration?.state?.showReorderHandle);
});
</script>

<template>
  <NodeViewWrapper
    as="div"
    class="segment-block"
    data-segment-block=""
    :data-segment-id="segmentId"
  >
    <div class="segment-block-gutter">
      <span
        class="segment-reorder-handle"
        contenteditable="false"
        draggable="false"
        data-segment-block-handle=""
        :data-segment-id="segmentId"
        :data-visible="showReorderHandle ? 'true' : 'false'"
      >
        <span class="segment-reorder-line-number">{{ lineNumberLabel }}</span>
        <span
          class="segment-reorder-grip"
          aria-hidden="true"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            class="lucide lucide-grip-vertical"
          >
            <circle
              cx="9"
              cy="12"
              r="1"
            />
            <circle
              cx="9"
              cy="5"
              r="1"
            />
            <circle
              cx="9"
              cy="19"
              r="1"
            />
            <circle
              cx="15"
              cy="12"
              r="1"
            />
            <circle
              cx="15"
              cy="5"
              r="1"
            />
            <circle
              cx="15"
              cy="19"
              r="1"
            />
          </svg>
        </span>
      </span>
    </div>
    <NodeViewContent
      as="div"
      class="segment-block-content"
    />
  </NodeViewWrapper>
</template>
