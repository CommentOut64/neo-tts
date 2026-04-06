<script setup lang="ts">
import { computed } from "vue";
import { ElMessage } from "element-plus";
import { useWorkspaceLightEdit } from "@/composables/useWorkspaceLightEdit";
import { rerenderSegment, updateSegment } from "@/api/editSession";
import { useEditSession, type SessionStatus } from "@/composables/useEditSession";
import { useRuntimeState } from "@/composables/useRuntimeState";
import { createSegmentRerenderQueue } from "./segmentRerenderQueue";
import { resolveMainActionButtonState } from "./mainActionButtonState";
import { resolveRerenderTargets } from "./rerenderTargets";
import { useParameterPanel } from "@/composables/useParameterPanel";

const props = defineProps<{
  sessionStatus: SessionStatus;
}>();

const lightEdit = useWorkspaceLightEdit();
const editSession = useEditSession();
const parameterPanel = useParameterPanel();
const { refreshSnapshot, refreshTimeline } = editSession;
const runtimeState = useRuntimeState();
const rerenderTargets = computed(() =>
  resolveRerenderTargets({
    dirtyTextSegmentIds: lightEdit.dirtySegmentIds.value,
    segments: editSession.segments.value.map((segment) => ({
      segment_id: segment.segment_id,
      order_key: segment.order_key,
      render_status: segment.render_status,
    })),
  }),
);
const queue = createSegmentRerenderQueue({
  submitSegmentUpdate: async (segmentId) => {
    const draftText = lightEdit.getDraft(segmentId);
    const targetSegment = editSession.segments.value.find(
      (segment) => segment.segment_id === segmentId,
    );

    if (draftText === undefined && (!targetSegment || targetSegment.render_status === "ready")) {
      return null;
    }

    const jobResponse = draftText !== undefined
      ? await updateSegment(segmentId, { raw_text: draftText })
      : await rerenderSegment(segmentId);

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
    dirtyCount: rerenderTargets.value.count,
    canInitialize: false,
    canMutate: runtimeState.canMutate.value,
  }),
);

const handleStart = async () => {
  const dirtyIds = rerenderTargets.value.segmentIds;
  if (dirtyIds.length === 0) return;
  await queue.run(dirtyIds);
};

const onClick = async () => {
  if (buttonState.value.disabled) {
    return;
  }

  if (parameterPanel.hasDirty.value) {
    parameterPanel.triggerFlash();
    // “不能只起提醒作用”，除了高亮外还要阻止重推理以防用旧参数空跑
    ElMessage.warning('请先提交或放弃暂存的参数配置');
    return;
  }

  await handleStart();
};
</script>

<template>
  <button
    :disabled="buttonState.disabled"
    @click="onClick"
    class="flex justify-center items-center gap-2 px-4 h-16 rounded-card font-semibold transition-all duration-300 min-w-[140px] text-center shadow-card shrink-0"
    :class="{
      'bg-cta hover:bg-cta/90 text-white':
        buttonState.mode === 'init' && !buttonState.disabled,
      'bg-amber-500 hover:bg-amber-600 text-white':
        buttonState.mode === 'rerender' && !buttonState.disabled,
      'bg-secondary/50 text-muted-fg cursor-not-allowed': buttonState.disabled,
    }"
  >
    <!-- <span
      v-if="buttonState.mode === 'rerender' && rerenderTargets.count > 0"
      class="i-lucide-wand-2 w-4 h-4"
    ></span> -->
    {{ buttonState.label }}
  </button>
</template>
