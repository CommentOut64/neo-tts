import { SegmentDecoration } from "./segmentDecoration";
import { SegmentEditingGuards } from "./segmentEditingGuards";

/**
 * 构建 WorkspaceEditorHost 专用的 TipTap 扩展列表。
 * 当前只包含段级 Decoration 扩展。
 */
export function buildEditorExtensions() {
  return [SegmentDecoration, SegmentEditingGuards];
}
