<script setup lang="ts">
import { computed } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";

import { useParameterPanel } from "@/composables/useParameterPanel";
import { useWorkspaceProcessing } from "@/composables/useWorkspaceProcessing";
import { useWorkspaceReorderDraft } from "@/composables/useWorkspaceReorderDraft";
import type { RegistryBindingOption } from "@/types/ttsRegistry";
import { shouldConfirmGlobalParameterSubmit } from "./parameter-panel/resolveParameterScope";

import BatchParameterPanel from "./BatchParameterPanel.vue";
import EdgeParameterPanel from "./EdgeParameterPanel.vue";
import ParameterDraftBar from "./ParameterDraftBar.vue";
import ParameterDraftConfirm from "./ParameterDraftConfirm.vue";
import SegmentParameterPanel from "./SegmentParameterPanel.vue";
import SessionParameterPanel from "./SessionParameterPanel.vue";

const props = defineProps<{
  bindings: RegistryBindingOption[];
}>();

const panel = useParameterPanel();
const workspaceProcessing = useWorkspaceProcessing();
const reorderDraft = useWorkspaceReorderDraft();

const scope = computed(() => panel.scopeContext.value.scope);
const hasDirty = computed(() => panel.hasDirty.value);
const isSubmitting = computed(() => panel.isSubmitting.value);
const confirmVisible = computed(() => panel.confirmVisible.value);
const isLocked = computed(() => workspaceProcessing.isInteractionLocked.value);
const isReorderLocked = computed(
  () => reorderDraft.hasDraft.value || reorderDraft.isSubmitting.value,
);

async function confirmGlobalParameterSubmitIfNeeded() {
  if (!shouldConfirmGlobalParameterSubmit(panel.scopeContext.value)) {
    return true;
  }

  try {
    await ElMessageBox.confirm(
      "您未选中任何段，是否对全局参数做出改动？",
      "确认修改全局参数",
      {
        confirmButtonText: "确认提交",
        cancelButtonText: "取消",
        type: "warning",
        closeOnClickModal: false,
        closeOnPressEscape: false,
        lockScroll: false,
      },
    );
    return true;
  } catch {
    return false;
  }
}

async function handleSubmit() {
  try {
    if (!(await confirmGlobalParameterSubmitIfNeeded())) {
      return;
    }
    await panel.submitDraft();
    if (scope.value !== "edge") {
      ElMessage.success("参数已提交");
    }
  } catch (error) {
    if (scope.value !== "edge") {
      ElMessage.error(error instanceof Error ? error.message : "参数提交失败");
    }
  }
}

async function handleSubmitAndContinue() {
  try {
    if (!(await confirmGlobalParameterSubmitIfNeeded())) {
      return;
    }
    await panel.submitAndContinue();
    if (scope.value !== "edge") {
      ElMessage.success("参数已提交");
    }
  } catch (error) {
    if (scope.value !== "edge") {
      ElMessage.error(error instanceof Error ? error.message : "参数提交失败");
    }
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
    <div class="relative">
      <div
        class="space-y-5"
        :class="isReorderLocked ? 'pointer-events-none select-none opacity-60' : ''"
      >
        <ParameterDraftBar
          :scope="scope"
          :has-dirty="hasDirty"
          :is-submitting="isSubmitting"
          :disabled="isLocked || isReorderLocked"
          @discard="panel.discardDraft()"
          @submit="handleSubmit"
        />

        <SessionParameterPanel v-if="scope === 'session'" :bindings="props.bindings" />
        <SegmentParameterPanel v-else-if="scope === 'segment'" :bindings="props.bindings" />
        <BatchParameterPanel v-else-if="scope === 'batch'" :bindings="props.bindings" />
        <EdgeParameterPanel v-else />

        <ParameterDraftConfirm
          :visible="confirmVisible"
          @cancel="panel.cancelPendingScopeChange()"
          @discard="handleDiscardAndContinue"
          @submit="handleSubmitAndContinue"
        />
      </div>

      <div
        v-if="isReorderLocked"
        class="absolute inset-0 z-10 cursor-not-allowed"
      ></div>
    </div>
  </div>
</template>
