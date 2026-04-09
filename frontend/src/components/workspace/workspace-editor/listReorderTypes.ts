export type DragReorderMode =
  | "idle"
  | "pending-drag"
  | "dragging"
  | "submitting";

export type ListDropIntent =
  | "swap"
  | "insert-before"
  | "insert-after";

export interface ListDropRectLike {
  top: number;
  bottom: number;
  height: number;
}
