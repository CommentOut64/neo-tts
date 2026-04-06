<script setup lang="ts">
import { computed } from "vue";
import { ElMessage } from "element-plus";

import { useParameterPanel } from "@/composables/useParameterPanel";
import type { VoiceProfile } from "@/types/tts";

import BatchParameterPanel from "./BatchParameterPanel.vue";
import EdgeParameterPanel from "./EdgeParameterPanel.vue";
import ParameterDraftBar from "./ParameterDraftBar.vue";
import ParameterDraftConfirm from "./ParameterDraftConfirm.vue";
import SegmentParameterPanel from "./SegmentParameterPanel.vue";
import SessionParameterPanel from "./SessionParameterPanel.vue";

const props = defineProps<{
  voices: VoiceProfile[];
}>();

const panel = useParameterPanel();

const scope = computed(() => panel.scopeContext.value.scope);
const hasDirty = computed(() => panel.hasDirty.value);
const isSubmitting = computed(() => panel.isSubmitting.value);
const confirmVisible = computed(() => panel.confirmVisible.value);

async function handleSubmit() {
  try {
    await panel.submitDraft();
    ElMessage.success("参数已提交");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "参数提交失败");
  }
}

async function handleSubmitAndContinue() {
  try {
    await panel.submitAndContinue();
    ElMessage.success("参数已提交");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "参数提交失败");
  }
}

async function handleDiscardAndContinue() {
  await panel.discardAndContinue();
}
</script>

<template>
  <div
    class="space-y-5 w-full h-full overflow-y-auto scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent"
  >
    <SessionParameterPanel v-if="scope === 'session'" :voices="props.voices" />
    <SegmentParameterPanel v-else-if="scope === 'segment'" :voices="props.voices" />
    <BatchParameterPanel v-else-if="scope === 'batch'" :voices="props.voices" />
    <EdgeParameterPanel v-else />

    <ParameterDraftBar
      :scope="scope"
      :has-dirty="hasDirty"
      :is-submitting="isSubmitting"
      @discard="panel.discardDraft()"
      @submit="handleSubmit"
    />

    <ParameterDraftConfirm
      :visible="confirmVisible"
      @cancel="panel.cancelPendingScopeChange()"
      @discard="handleDiscardAndContinue"
      @submit="handleSubmitAndContinue"
    />
  </div>
</template>
