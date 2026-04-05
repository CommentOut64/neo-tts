import { SegmentDecoration } from './segmentDecoration'

/**
 * 构建 WorkspaceEditorHost 专用的 TipTap 扩展列表。
 * 当前只包含段级 Decoration 扩展。
 */
export function buildEditorExtensions() {
  return [SegmentDecoration]
}
