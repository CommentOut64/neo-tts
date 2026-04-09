import type { ListDropIntent, ListDropRectLike } from "./listReorderTypes";

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export function computeListDropIntent(input: {
  clientY: number;
  rect: ListDropRectLike;
  draggingSegmentId: string | null;
  targetSegmentId: string | null;
}): ListDropIntent | null {
  if (
    !input.targetSegmentId ||
    !input.draggingSegmentId ||
    input.draggingSegmentId === input.targetSegmentId
  ) {
    return null;
  }

  const edgeZone = clamp(input.rect.height * 0.22, 8, 14);
  if (input.clientY < input.rect.top + edgeZone) {
    return "insert-before";
  }
  if (input.clientY > input.rect.bottom - edgeZone) {
    return "insert-after";
  }
  return "swap";
}
