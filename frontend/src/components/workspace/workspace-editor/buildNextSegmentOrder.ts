import type { ListDropIntent } from "./listReorderTypes";

function arraysEqual(left: string[], right: string[]) {
  return (
    left.length === right.length &&
    left.every((value, index) => value === right[index])
  );
}

export function buildNextSegmentOrder(input: {
  currentOrder: string[];
  draggingSegmentId: string | null;
  dropTargetSegmentId: string | null;
  dropIntent: ListDropIntent | null;
}): string[] {
  const {
    currentOrder,
    draggingSegmentId,
    dropTargetSegmentId,
    dropIntent,
  } = input;

  if (
    !draggingSegmentId ||
    !dropTargetSegmentId ||
    !dropIntent ||
    draggingSegmentId === dropTargetSegmentId
  ) {
    return [...currentOrder];
  }

  const draggingIndex = currentOrder.indexOf(draggingSegmentId);
  const targetIndex = currentOrder.indexOf(dropTargetSegmentId);
  if (draggingIndex < 0 || targetIndex < 0) {
    return [...currentOrder];
  }

  if (dropIntent === "swap") {
    const nextOrder = [...currentOrder];
    nextOrder[draggingIndex] = dropTargetSegmentId;
    nextOrder[targetIndex] = draggingSegmentId;
    return nextOrder;
  }

  const remaining = currentOrder.filter((segmentId) => segmentId !== draggingSegmentId);
  const targetIndexInRemaining = remaining.indexOf(dropTargetSegmentId);
  if (targetIndexInRemaining < 0) {
    return [...currentOrder];
  }

  const insertIndex =
    dropIntent === "insert-before"
      ? targetIndexInRemaining
      : targetIndexInRemaining + 1;
  const nextOrder = [...remaining];
  nextOrder.splice(insertIndex, 0, draggingSegmentId);

  return arraysEqual(nextOrder, currentOrder) ? [...currentOrder] : nextOrder;
}
