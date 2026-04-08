<script setup lang="ts">
import { computed } from "vue";

import { useEditSession } from "@/composables/useEditSession";
import { useParameterPanel } from "@/composables/useParameterPanel";
import { useSegmentSelection } from "@/composables/useSegmentSelection";
import type { VoiceProfile } from "@/types/tts";

import SharedParameterScopePanel from "./parameter-panel/SharedParameterScopePanel.vue";

const props = defineProps<{
  voices: VoiceProfile[];
}>();

const editSession = useEditSession();
const panel = useParameterPanel();
const selection = useSegmentSelection();

const selectedSegmentId = computed(() => panel.scopeContext.value.segmentIds[0] ?? null);
const adjacentEdges = computed(() => {
  if (!selectedSegmentId.value) return [];
  return editSession.edges.value.filter(
    (edge) =>
      edge.left_segment_id === selectedSegmentId.value ||
      edge.right_segment_id === selectedSegmentId.value,
  );
});
</script>

<template>
  <SharedParameterScopePanel
    :voices="props.voices"
    title="段级参数"
    hint="当前选中段的运行期参数。提交后仅持久化配置，后续推理会继承这些值。"
  />

  <!-- TODO: 暂时隐藏相邻边设置卡片 -->
  <section v-if="false && adjacentEdges.length > 0" class="bg-card rounded-card p-4 shadow-card border border-border dark:border-transparent">
    <h3 class="text-[13px] font-semibold text-foreground mb-3">相邻边</h3>
    <div class="flex flex-col gap-2">
      <button
        v-for="edge in adjacentEdges"
        :key="edge.edge_id"
        class="hover-state-layer px-3 py-2 text-left rounded border border-border text-sm text-foreground transition-colors"
        @click="selection.selectEdge(edge.edge_id)"
      >
        {{ edge.left_segment_id }} ↔ {{ edge.right_segment_id }}
      </button>
    </div>
  </section>
</template>
