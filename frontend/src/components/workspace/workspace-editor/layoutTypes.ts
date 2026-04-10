import type { JSONContent } from "@tiptap/vue-3";

import type { WorkspaceCompositionLayoutHints } from "./compositionLayoutHints";

export type WorkspaceEditorLayoutMode = "list" | "composition";

export interface WorkspaceSemanticSegment {
  segmentId: string;
  orderKey: number;
  text: string;
  renderStatus: "pending" | "completed";
  isDirty: boolean;
}

export interface WorkspaceSemanticEdge {
  edgeId: string | null;
  leftSegmentId: string;
  rightSegmentId: string;
  pauseDurationSeconds: number | null;
  boundaryStrategy: string | null;
}

export interface WorkspaceSourceBlock {
  blockId: string;
  rawLineText: string;
  segmentIds: string[];
}

export interface CompositionAvailability {
  ready: boolean;
  reason: string | null;
}

export interface WorkspaceSemanticDocument {
  segmentOrder: string[];
  segmentsById: Record<string, WorkspaceSemanticSegment>;
  edgesByLeftSegmentId: Record<string, WorkspaceSemanticEdge>;
  sourceBlocks: WorkspaceSourceBlock[];
  compositionAvailability: CompositionAvailability;
}

export interface SegmentRenderRange {
  segmentId: string;
  from: number;
  to: number;
}

export interface EdgeRenderAnchor {
  edgeId: string | null;
  leftSegmentId: string;
  rightSegmentId: string;
  from: number;
  to: number;
  layoutMode: WorkspaceEditorLayoutMode;
  crossBlock: boolean;
}

export interface WorkspaceRenderMap {
  orderedSegmentIds: string[];
  segmentRanges: SegmentRenderRange[];
  edgeAnchors: EdgeRenderAnchor[];
}

export interface WorkspaceRenderPlan {
  layoutMode: WorkspaceEditorLayoutMode;
  doc: JSONContent;
  renderMap: WorkspaceRenderMap;
}

export interface WorkspaceSemanticSegmentInput {
  segmentId: string;
  orderKey: number;
  text: string;
  renderStatus: "pending" | "completed";
}

export interface WorkspaceSemanticEdgeInput {
  edgeId: string | null;
  leftSegmentId: string;
  rightSegmentId: string;
  pauseDurationSeconds: number | null;
  boundaryStrategy: string | null;
}

export interface BuildWorkspaceSemanticDocumentInput {
  sourceText: string | null;
  compositionLayoutHints?: WorkspaceCompositionLayoutHints | null;
  segments: WorkspaceSemanticSegmentInput[];
  edges?: WorkspaceSemanticEdgeInput[];
  dirtySegmentIds?: ReadonlySet<string>;
}
