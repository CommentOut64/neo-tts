<script setup lang="ts">
import { ref, computed } from "vue";
import { useWorkspaceLightEdit } from "@/composables/useWorkspaceLightEdit";
import { updateSegment, subscribeRenderJobEvents } from "@/api/editSession";
import { useEditSession } from "@/composables/useEditSession";
import { useRuntimeState } from "@/composables/useRuntimeState";
import type { RenderJob, RenderJobEventType } from "@/types/editSession";

const lightEdit = useWorkspaceLightEdit();
const { refreshSnapshot, refreshTimeline } = useEditSession();
const runtimeState = useRuntimeState();

// State machine
// idle -> processing -> idle
const isProcessing = ref(false);
const totalJobs = ref(0);
const currentJobIndex = ref(0);
const isCancelling = ref(false);

// Abort controller mechanism for the queue
let abortQueue = false;
let currentEventSourceCloser: (() => void) | null = null;

const label = computed(() => {
  if (isCancelling.value) return "取消中...";
  if (isProcessing.value)
    return `重推理中 (${currentJobIndex.value + 1}/${totalJobs.value})`;
  if (lightEdit.dirtyCount.value > 0)
    return `应用修改 (${lightEdit.dirtyCount.value})`;
  return "当前已是最新";
});

const isDisabled = computed(() => {
  if (isCancelling.value) return true;
  if (!isProcessing.value && lightEdit.dirtyCount.value === 0) return true;
  return false;
});

const handleStart = async () => {
  const dirtyIds = Array.from(lightEdit.dirtySegmentIds.value);
  if (dirtyIds.length === 0) return;

  isProcessing.value = true;
  isCancelling.value = false;
  totalJobs.value = dirtyIds.length;
  abortQueue = false;

  let completedAny = false;

  for (let i = 0; i < dirtyIds.length; i++) {
    if (abortQueue) break;

    currentJobIndex.value = i;
    const segId = dirtyIds[i];
    const textToSubmit = lightEdit.getDraft(segId);

    if (textToSubmit === undefined) {
      continue; // Safety check
    }

    try {
      // 1. Submit the patch
      const jobResponse = await updateSegment(segId, { raw_text: textToSubmit });
      runtimeState.trackJob(jobResponse.job_id);

      // 2. Wait for completion via SSE
      await new Promise<void>((resolve, reject) => {
        if (abortQueue) {
          reject(new Error("Aborted by user"));
          return;
        }

        const closer = subscribeRenderJobEvents(jobResponse.job_id, {
          onEvent: (type: RenderJobEventType, payload: unknown) => {
            if (type === "job_state_changed") {
              const job = payload as RenderJob;
              if (job.status === "completed") {
                lightEdit.clearDraft(segId);
                completedAny = true;
                cleanup();
                resolve();
                return;
              }

              if (
                job.status === "failed" ||
                job.status === "cancelled_partial" ||
                job.status === "paused"
              ) {
                cleanup();
                reject(new Error(`Job ended with status: ${job.status}`));
              }
            } else if (
              type === "job_cancelled_partial" ||
              type === "job_paused"
            ) {
              cleanup();
              reject(new Error(`Job ended with status: ${type}`));
            }
          },
          onError: (err) => {
            cleanup();
            reject(err);
          },
        });

        const cleanup = () => {
          closer();
          currentEventSourceCloser = null;
        };

        currentEventSourceCloser = cleanup;
      });
    } catch (err: any) {
      console.warn(`Failed or aborted segment ${segId}:`, err);
      // Stop the queue if one fails or aborted
      break;
    }
  }

  // Reload timeline if any jobs succeeded
  if (completedAny) {
    try {
      await refreshSnapshot();
      await refreshTimeline();
    } catch (err) {
      console.error("Failed to refresh session after queue completion", err);
    }
  }

  isProcessing.value = false;
  isCancelling.value = false;
  currentEventSourceCloser = null;
};

const handleCancel = () => {
  if (isProcessing.value && !isCancelling.value) {
    isCancelling.value = true;
    abortQueue = true;
    if (currentEventSourceCloser) {
      currentEventSourceCloser();
      currentEventSourceCloser = null;
    }
  }
};

const onClick = () => {
  if (isProcessing.value) {
    handleCancel();
  } else {
    handleStart();
  }
};
</script>

<template>
  <button
    :disabled="isDisabled"
    @click="onClick"
    class="px-4 py-2 rounded-lg font-semibold transition-all duration-300 min-w-[140px] text-center shadow-sm"
    :class="{
      'bg-amber-500 hover:bg-amber-600 text-white':
        !isProcessing && lightEdit.dirtyCount > 0,
      'bg-red-500 hover:bg-red-600 text-white animate-pulse':
        isProcessing && !isCancelling,
      'bg-secondary/50 text-muted-fg cursor-not-allowed': isDisabled,
    }"
  >
    <div class="flex items-center justify-center gap-2">
      <span
        v-if="isProcessing && !isCancelling"
        class="i-lucide-loader-2 animate-spin w-4 h-4"
      ></span>
      <span
        v-if="!isProcessing && lightEdit.dirtyCount > 0"
        class="i-lucide-wand-2 w-4 h-4"
      ></span>
      <span>{{ label }}</span>
    </div>
  </button>
</template>
