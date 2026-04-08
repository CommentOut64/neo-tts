import { PauseBoundary } from "./pauseBoundary";
import { SegmentAnchorMark } from "./segmentAnchorMark";
import { SegmentDecoration } from "./segmentDecoration";
import { SegmentEditingGuards } from "./segmentEditingGuards";

export interface WorkspaceEditorExtensionOptions {
  onActivateEdge: (edgeId: string | null) => void;
}

export function buildEditorExtensions(
  options: WorkspaceEditorExtensionOptions,
) {
  return [
    SegmentAnchorMark,
    PauseBoundary.configure({
      onActivateEdge: options.onActivateEdge,
    }),
    SegmentDecoration,
    SegmentEditingGuards,
  ];
}
