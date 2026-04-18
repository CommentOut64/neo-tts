<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { useWorkspaceLightEdit } from "@/composables/useWorkspaceLightEdit";
import { rerenderSegment, updateSegment } from "@/api/editSession";
import { useEditSession, type SessionStatus } from "@/composables/useEditSession";
import { useRuntimeState } from "@/composables/useRuntimeState";
import { createSegmentRerenderQueue } from "./segmentRerenderQueue";
import { resolveMainActionButtonState } from "./mainActionButtonState";
import { resolveRerenderTargets } from "./rerenderTargets";
import { useParameterPanel } from "@/composables/useParameterPanel";
import { useWorkspaceProcessing } from "@/composables/useWorkspaceProcessing";
import { useWorkspaceReorderDraft } from "@/composables/useWorkspaceReorderDraft";

const props = defineProps<{
  sessionStatus: SessionStatus;
}>();

const lightEdit = useWorkspaceLightEdit();
const editSession = useEditSession();
const parameterPanel = useParameterPanel();
const {
  refreshFormalSessionState,
  appliedText,
  backfillInputDraftFromAppliedText,
} = editSession;
const runtimeState = useRuntimeState();
const workspaceProcessing = useWorkspaceProcessing();
const reorderDraft = useWorkspaceReorderDraft();
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

    const textPatch = draftText !== undefined
      ? {
          stem: draftText.stem,
          terminal_raw: draftText.terminal_raw,
          terminal_closer_suffix: draftText.terminal_closer_suffix,
          terminal_source: draftText.terminal_source,
        }
      : null;

    const jobResponse = draftText !== undefined
      ? await updateSegment(segmentId, { text_patch: textPatch ?? undefined })
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
    await refreshFormalSessionState();
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
    hasReorderDraft: reorderDraft.hasDraft.value,
    canInitialize: false,
    canMutate: runtimeState.canMutate.value && !workspaceProcessing.isInteractionLocked.value,
  }),
);
const canShowDiscardBubble = computed(
  () =>
    buttonState.value.mode === "apply_reorder" &&
    reorderDraft.hasDraft.value &&
    !buttonState.value.disabled,
);
const discardBubbleVisible = ref(false);

let showDiscardBubbleTimer: ReturnType<typeof setTimeout> | null = null;
let hideDiscardBubbleTimer: ReturnType<typeof setTimeout> | null = null;

function clearDiscardBubbleTimers() {
  if (showDiscardBubbleTimer) {
    clearTimeout(showDiscardBubbleTimer);
    showDiscardBubbleTimer = null;
  }
  if (hideDiscardBubbleTimer) {
    clearTimeout(hideDiscardBubbleTimer);
    hideDiscardBubbleTimer = null;
  }
}

function hideDiscardBubbleImmediately() {
  clearDiscardBubbleTimers();
  discardBubbleVisible.value = false;
}

function scheduleDiscardBubbleOpen() {
  if (!canShowDiscardBubble.value) {
    return;
  }
  if (hideDiscardBubbleTimer) {
    clearTimeout(hideDiscardBubbleTimer);
    hideDiscardBubbleTimer = null;
  }
  if (discardBubbleVisible.value || showDiscardBubbleTimer) {
    return;
  }
  showDiscardBubbleTimer = setTimeout(() => {
    showDiscardBubbleTimer = null;
    discardBubbleVisible.value = true;
  }, 120);
}

function scheduleDiscardBubbleClose() {
  if (showDiscardBubbleTimer) {
    clearTimeout(showDiscardBubbleTimer);
    showDiscardBubbleTimer = null;
  }
  if (!discardBubbleVisible.value || hideDiscardBubbleTimer) {
    return;
  }
  hideDiscardBubbleTimer = setTimeout(() => {
    hideDiscardBubbleTimer = null;
    discardBubbleVisible.value = false;
  }, 220);
}

watch(
  canShowDiscardBubble,
  (nextValue) => {
    if (!nextValue) {
      hideDiscardBubbleImmediately();
    }
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  clearDiscardBubbleTimers();
});

const handleStart = async () => {
  const dirtyIds = rerenderTargets.value.segmentIds;
  if (dirtyIds.length === 0) return;
  const result = await queue.run(dirtyIds);
  if (
    result?.completedAll &&
    result.terminalStatus === "completed" &&
    appliedText.value
  ) {
    backfillInputDraftFromAppliedText(appliedText.value);
  }
};

const onClick = async () => {
  if (buttonState.value.disabled) {
    return;
  }

  if (buttonState.value.mode === "apply_reorder") {
    try {
      await reorderDraft.requestApplyDraft();
    } catch {
      return;
    }
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

function handleDiscardReorder() {
  reorderDraft.requestDiscardDraft();
  hideDiscardBubbleImmediately();
}
</script>

<template>
  <div
    class="relative shrink-0"
    @mouseenter="scheduleDiscardBubbleOpen"
    @mouseleave="scheduleDiscardBubbleClose"
  >
    <button
      :disabled="buttonState.disabled"
      @click="onClick"
      class="animate-fall flex justify-center items-center gap-2 px-4 h-16 rounded-card font-semibold transition-all duration-300 min-w-[140px] text-center shadow-card"
      :class="{
        'hover-state-layer': buttonState.mode !== 'rerender',
        'bg-cta text-white':
          buttonState.mode === 'init' && !buttonState.disabled,
        'bg-[#fc8c4a] hover:bg-[#e37e2e] dark:bg-[#e37e2e] dark:hover:bg-[#fc8c4a] text-white':
          buttonState.mode === 'rerender' && !buttonState.disabled,
        'bg-blue-500 hover:bg-blue-600 text-white':
          buttonState.mode === 'apply_reorder' && !buttonState.disabled,
        'bg-secondary/50 text-muted-fg cursor-not-allowed': buttonState.disabled,
      }"
    >
      {{ buttonState.label }}
    </button>

    <transition name="reorder-discard-bubble">
      <div
        v-if="canShowDiscardBubble && discardBubbleVisible"
        class="absolute bottom-full left-1/2 z-20 mb-3 -translate-x-1/2"
      >
        <button
          type="button"
          class="rounded-card border border-border/70 bg-card/95 px-4 py-2.5 text-xs font-medium text-muted-fg shadow-lg backdrop-blur whitespace-nowrap transition-colors hover:bg-secondary/60 hover:text-foreground"
          @click="handleDiscardReorder"
        >
          放弃重排
        </button>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.reorder-discard-bubble-enter-active,
.reorder-discard-bubble-leave-active {
  transition:
    opacity 0.2s cubic-bezier(0.16, 1, 0.3, 1),
    transform 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

.reorder-discard-bubble-enter-from,
.reorder-discard-bubble-leave-to {
  opacity: 0;
  transform: translate(-50%, 12px) scale(0.95);
}
</style>
