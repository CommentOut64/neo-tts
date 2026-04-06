<script setup lang="ts">
import { computed } from "vue";
import { ElMessage } from "element-plus";
import { useWorkspaceLightEdit } from "@/composables/useWorkspaceLightEdit";
import { updateSegment } from "@/api/editSession";
import { useEditSession, type SessionStatus } from "@/composables/useEditSession";
import { useRuntimeState } from "@/composables/useRuntimeState";
import { createSegmentRerenderQueue } from "./segmentRerenderQueue";
import { resolveMainActionButtonState } from "./mainActionButtonState";

const props = defineProps<{
  sessionStatus: SessionStatus;
}>();

const lightEdit = useWorkspaceLightEdit();
const { refreshSnapshot, refreshTimeline } = useEditSession();
const runtimeState = useRuntimeState();
const queue = createSegmentRerenderQueue({
  getDraftText: (segmentId) => lightEdit.getDraft(segmentId),
  submitSegmentUpdate: async (segmentId, text) => {
    const jobResponse = await updateSegment(segmentId, { raw_text: text });
    runtimeState.trackJob(jobResponse, {
      initialRendering: false,
      lockedSegmentIds: [segmentId],
      refreshSessionOnTerminal: false,
    });

    return {
      jobId: jobResponse.job_id,
      waitForTerminal: () => runtimeState.waitForJobTerminal(jobResponse.job_id),
      cancel: () => runtimeState.cancelJob(),
    };
  },
  clearDraft: (segmentId) => lightEdit.clearDraft(segmentId),
  refreshSession: async () => {
    await refreshSnapshot();
    await refreshTimeline();
  },
  setLockedSegments: (segmentIds) => {
    runtimeState.lockedSegmentIds.value = new Set(segmentIds);
  },
  onError: (error) => {
    console.warn("Segment rerender queue failed", error);
    if (error instanceof Error) {
      ElMessage.error(error.message);
    }
  },
});

const buttonState = computed(() =>
  resolveMainActionButtonState({
    sessionStatus: props.sessionStatus,
    dirtyCount: lightEdit.dirtyCount.value,
    canInitialize: false,
    canMutate: runtimeState.canMutate.value,
  }),
);

const handleStart = async () => {
  const dirtyIds = Array.from(lightEdit.dirtySegmentIds.value);
  if (dirtyIds.length === 0) return;
  await queue.run(dirtyIds);
};

const onClick = async () => {
  if (buttonState.value.disabled) {
    return;
  }

  await handleStart();
};
</script>

<template>
  <button
    :disabled="buttonState.disabled"
    @click="onClick"
    class="px-4 h-16 rounded-card font-semibold transition-all duration-300 min-w-[140px] text-center shadow-card shrink-0"
    :class="{
      'bg-cta hover:bg-cta/90 text-white':
        buttonState.mode === 'init' && !buttonState.disabled,
      'bg-amber-500 hover:bg-amber-600 text-white':
        buttonState.mode === 'rerender' && !buttonState.disabled,
      'bg-secondary/50 text-muted-fg cursor-not-allowed': buttonState.disabled,
    }"
  >
    <div class="flex items-center justify-center gap-2">
      <span
        v-if="buttonState.mode === 'rerender' && lightEdit.dirtyCount > 0"
        class="i-lucide-wand-2 w-4 h-4"
      ></span>
      <span>{{ buttonState.label }}</span>
    </div>
  </button>
</template>
