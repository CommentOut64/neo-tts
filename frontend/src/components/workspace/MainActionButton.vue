<script setup lang="ts">
import { ref, computed } from "vue";
import { ElMessage } from "element-plus";
import { useWorkspaceLightEdit } from "@/composables/useWorkspaceLightEdit";
import { updateSegment } from "@/api/editSession";
import { useEditSession } from "@/composables/useEditSession";
import { useRuntimeState } from "@/composables/useRuntimeState";
import { createSegmentRerenderQueue } from "./segmentRerenderQueue";

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

const label = computed(() => {
  if (queue.isCancelling.value) return "取消中...";
  if (queue.isProcessing.value)
    return `重推理中 (${queue.currentJobIndex.value + 1}/${queue.totalJobs.value})`;
  if (lightEdit.dirtyCount.value > 0)
    return `应用修改 (${lightEdit.dirtyCount.value})`;
  return "当前已是最新";
});

const isDisabled = computed(() => {
  if (queue.isCancelling.value) return true;
  if (!queue.isProcessing.value && lightEdit.dirtyCount.value === 0) return true;
  return false;
});

const handleStart = async () => {
  const dirtyIds = Array.from(lightEdit.dirtySegmentIds.value);
  if (dirtyIds.length === 0) return;
  await queue.run(dirtyIds);
};

const handleCancel = async () => {
  if (queue.isProcessing.value && !queue.isCancelling.value) {
    await queue.requestCancel();
  }
};

const onClick = async () => {
  if (queue.isProcessing.value) {
    await handleCancel();
  } else {
    await handleStart();
  }
};
</script>

<template>
  <button
    :disabled="isDisabled"
    @click="onClick"
    class="px-4 h-16 rounded-card font-semibold transition-all duration-300 min-w-[140px] text-center shadow-card shrink-0"
    :class="{
      'bg-amber-500 hover:bg-amber-600 text-white':
        !queue.isProcessing && lightEdit.dirtyCount > 0,
      'bg-red-500 hover:bg-red-600 text-white animate-pulse':
        queue.isProcessing && !queue.isCancelling,
      'bg-secondary/50 text-muted-fg cursor-not-allowed': isDisabled,
    }"
  >
    <div class="flex items-center justify-center gap-2">
      <span
        v-if="queue.isProcessing && !queue.isCancelling"
        class="i-lucide-loader-2 animate-spin w-4 h-4"
      ></span>
      <span
        v-if="!queue.isProcessing && lightEdit.dirtyCount > 0"
        class="i-lucide-wand-2 w-4 h-4"
      ></span>
      <span>{{ label }}</span>
    </div>
  </button>
</template>
