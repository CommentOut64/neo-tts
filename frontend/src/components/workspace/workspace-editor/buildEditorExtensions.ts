import { PauseBoundary } from "./pauseBoundary";
import { SegmentAnchorMark } from "./segmentAnchorMark";
import { SegmentBlock } from "./list/segmentBlock";
import { SegmentDecoration } from "./segmentDecoration";
import { SegmentEditingGuards } from "./segmentEditingGuards";
import { TerminalCapsuleMark } from "./terminalCapsuleMark";

export interface WorkspaceEditorExtensionOptions {
  onActivateEdge: (edgeId: string | null) => void;
  onProtectedTerminalCapsule?: () => void;
}

export function buildEditorExtensions(
  options: WorkspaceEditorExtensionOptions,
) {
  return [
    SegmentAnchorMark,
    TerminalCapsuleMark,
    SegmentBlock,
    PauseBoundary.configure({
      onActivateEdge: options.onActivateEdge,
    }),
    SegmentDecoration,
    SegmentEditingGuards.configure({
      onProtectedTerminalCapsule: options.onProtectedTerminalCapsule,
    }),
  ];
}
