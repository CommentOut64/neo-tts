import { nextTick, onBeforeUnmount, ref } from "vue";

import { buildNextSegmentOrder } from "@/components/workspace/workspace-editor/buildNextSegmentOrder";
import { computeListDropIntent } from "@/components/workspace/workspace-editor/computeListDropIntent";
import { resolveSegmentBlockElement } from "@/components/workspace/workspace-editor/resolveSegmentBlockElement";
import type {
  DragReorderMode,
  ListDropIntent,
} from "@/components/workspace/workspace-editor/listReorderTypes";

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function arraysEqual(left: string[], right: string[]) {
  return (
    left.length === right.length &&
    left.every((value, index) => value === right[index])
  );
}

export interface WorkspaceListReorderCommitPayload {
  nextOrder: string[];
  rollbackOrder: string[];
  draggingSegmentId: string;
  dropTargetSegmentId: string;
  dropIntent: ListDropIntent;
}

export interface UseWorkspaceListReorderOptions {
  canStartDrag: () => boolean;
  getCurrentOrder: () => string[];
  getScrollContainer: () => HTMLElement | null;
  onCommit: (payload: WorkspaceListReorderCommitPayload) => Promise<void>;
}

export function useWorkspaceListReorder(
  options: UseWorkspaceListReorderOptions,
) {
  const mode = ref<DragReorderMode>("idle");
  const draggingSegmentId = ref<string | null>(null);
  const dropTargetSegmentId = ref<string | null>(null);
  const dropIntent = ref<ListDropIntent | null>(null);
  const pointerClientX = ref<number | null>(null);
  const pointerClientY = ref<number | null>(null);
  const dragStartClientX = ref<number | null>(null);
  const dragStartClientY = ref<number | null>(null);
  const previewOrder = ref<string[] | null>(null);
  const rollbackOrder = ref<string[] | null>(null);
  const suppressNextClick = ref(false);

  function clearDocumentListeners() {
    document.removeEventListener("pointermove", handlePointerMove);
    document.removeEventListener("pointerup", handlePointerUp);
    document.removeEventListener("pointercancel", handlePointerCancel);
  }

  function resetDragState(nextMode: DragReorderMode = "idle") {
    mode.value = nextMode;
    draggingSegmentId.value = null;
    dropTargetSegmentId.value = null;
    dropIntent.value = null;
    pointerClientX.value = null;
    pointerClientY.value = null;
    dragStartClientX.value = null;
    dragStartClientY.value = null;
    clearDocumentListeners();
  }

  function autoScrollIfNeeded(clientY: number) {
    const container = options.getScrollContainer();
    if (!container) {
      return;
    }

    const rect = container.getBoundingClientRect();
    const threshold = 40;
    let delta = 0;

    if (clientY < rect.top + threshold) {
      delta = -clamp(rect.top + threshold - clientY, 6, 22);
    } else if (clientY > rect.bottom - threshold) {
      delta = clamp(clientY - (rect.bottom - threshold), 6, 22);
    }

    if (delta !== 0) {
      container.scrollTop += delta;
    }
  }

  function syncDropTarget(clientX: number, clientY: number) {
    const target = document.elementFromPoint(clientX, clientY);
    const segmentBlock = resolveSegmentBlockElement(target);
    const targetSegmentId = segmentBlock?.dataset.segmentId ?? null;

    if (!targetSegmentId) {
      dropTargetSegmentId.value = null;
      dropIntent.value = null;
      return;
    }

    dropTargetSegmentId.value = targetSegmentId;
    dropIntent.value = computeListDropIntent({
      clientY,
      rect: segmentBlock.getBoundingClientRect(),
      draggingSegmentId: draggingSegmentId.value,
      targetSegmentId,
    });
  }

  async function submitDrop() {
    const currentOrder = options.getCurrentOrder();
    const draggingId = draggingSegmentId.value;
    const targetId = dropTargetSegmentId.value;
    const intent = dropIntent.value;
    const nextOrder = buildNextSegmentOrder({
      currentOrder,
      draggingSegmentId: draggingId,
      dropTargetSegmentId: targetId,
      dropIntent: intent,
    });

    if (
      !draggingId ||
      !targetId ||
      !intent ||
      arraysEqual(nextOrder, currentOrder)
    ) {
      resetDragState();
      return;
    }

    const currentRollbackOrder = [...currentOrder];
    rollbackOrder.value = currentRollbackOrder;
    previewOrder.value = nextOrder;
    resetDragState("submitting");

    try {
      await options.onCommit({
        nextOrder,
        rollbackOrder: currentRollbackOrder,
        draggingSegmentId: draggingId,
        dropTargetSegmentId: targetId,
        dropIntent: intent,
      });
      previewOrder.value = null;
      rollbackOrder.value = null;
      mode.value = "idle";
    } catch (error) {
      previewOrder.value = currentRollbackOrder;
      await nextTick();
      previewOrder.value = null;
      rollbackOrder.value = null;
      mode.value = "idle";
      throw error;
    }
  }

  function handlePointerMove(event: PointerEvent) {
    if (
      mode.value !== "pending-drag" &&
      mode.value !== "dragging"
    ) {
      return;
    }

    pointerClientX.value = event.clientX;
    pointerClientY.value = event.clientY;

    if (mode.value === "pending-drag") {
      const deltaX = event.clientX - (dragStartClientX.value ?? event.clientX);
      const deltaY = event.clientY - (dragStartClientY.value ?? event.clientY);
      const distance = Math.hypot(deltaX, deltaY);
      if (distance < 4) {
        return;
      }
      mode.value = "dragging";
    }

    event.preventDefault();
    autoScrollIfNeeded(event.clientY);
    syncDropTarget(event.clientX, event.clientY);
  }

  function handlePointerCancel() {
    resetDragState();
  }

  function handlePointerUp(event: PointerEvent) {
    if (mode.value === "pending-drag") {
      resetDragState();
      return;
    }

    if (mode.value !== "dragging") {
      resetDragState();
      return;
    }

    event.preventDefault();
    void submitDrop().catch(() => undefined);
  }

  function startCandidateDrag(event: PointerEvent, segmentId: string) {
    if (!options.canStartDrag() || mode.value === "submitting") {
      return false;
    }

    const currentOrder = options.getCurrentOrder();
    if (!segmentId || !currentOrder.includes(segmentId)) {
      return false;
    }

    event.preventDefault();
    event.stopPropagation();

    suppressNextClick.value = true;
    draggingSegmentId.value = segmentId;
    dropTargetSegmentId.value = null;
    dropIntent.value = null;
    pointerClientX.value = event.clientX;
    pointerClientY.value = event.clientY;
    dragStartClientX.value = event.clientX;
    dragStartClientY.value = event.clientY;
    mode.value = "pending-drag";

    document.addEventListener("pointermove", handlePointerMove, {
      passive: false,
    });
    document.addEventListener("pointerup", handlePointerUp, {
      passive: false,
    });
    document.addEventListener("pointercancel", handlePointerCancel);
    return true;
  }

  function consumeClickSuppression() {
    if (!suppressNextClick.value) {
      return false;
    }
    suppressNextClick.value = false;
    return true;
  }

  function resetState() {
    previewOrder.value = null;
    rollbackOrder.value = null;
    suppressNextClick.value = false;
    resetDragState();
  }

  onBeforeUnmount(() => {
    clearDocumentListeners();
  });

  return {
    mode,
    draggingSegmentId,
    dropTargetSegmentId,
    dropIntent,
    pointerClientX,
    pointerClientY,
    dragStartClientX,
    dragStartClientY,
    previewOrder,
    rollbackOrder,
    startCandidateDrag,
    consumeClickSuppression,
    resetState,
  };
}
