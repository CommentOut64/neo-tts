import type { JSONContent } from "@tiptap/vue-3";

import type { EditableEdge, EditableSegment } from "@/types/editSession";

import { findNodeAtPosition } from "./extractRenderMapFromDoc";
import type { WorkspaceEditorLayoutMode, WorkspaceRenderMap } from "./layoutTypes";

type ClosestCapableTarget = {
  closest: (selector: string) => ClosestCapableTarget | null;
  getAttribute: (name: string) => string | null;
};

export function requestLayoutMode(input: {
  isEditing: boolean;
  currentMode: WorkspaceEditorLayoutMode;
  nextMode: WorkspaceEditorLayoutMode;
}): {
  layoutMode: WorkspaceEditorLayoutMode;
  warning: string | null;
} {
  if (input.isEditing) {
    return {
      layoutMode: input.currentMode,
      warning: "请先完成或放弃当前编辑，再切换布局",
    };
  }

  return {
    layoutMode: input.nextMode,
    warning: null,
  };
}

export function buildWorkspaceViewRevisionKey(input: {
  layoutMode: WorkspaceEditorLayoutMode;
  sourceDocRevision: number;
  edgeTopologyRevision: number;
  layoutHintRevision: number;
}): string {
  return [
    input.layoutMode,
    String(input.sourceDocRevision),
    String(input.edgeTopologyRevision),
    String(input.layoutHintRevision),
  ].join(":");
}

export function buildWorkspaceDraftPersistKey(input: {
  documentVersion: number;
  mode: "editing" | "preview";
  sourceDocRevision: number;
  layoutHintRevision: number;
}): string {
  return [
    String(input.documentVersion),
    input.mode,
    String(input.sourceDocRevision),
    String(input.layoutHintRevision),
  ].join(":");
}

export function resolveWorkspaceSessionItems<T>(input: {
  snapshotDocumentVersion: number | null | undefined;
  currentDocumentVersion: number | null;
  snapshotItems: T[] | null | undefined;
  liveItems: T[];
}): T[] {
  if (
    input.snapshotDocumentVersion === input.currentDocumentVersion &&
    Array.isArray(input.snapshotItems) &&
    input.snapshotItems.length > 0
  ) {
    return input.snapshotItems;
  }

  return input.liveItems;
}

export function cloneWorkspaceSerializable<T>(value: T): T {
  if (value === null || value === undefined) {
    return value;
  }

  if (typeof value !== "object") {
    return value;
  }

  return JSON.parse(JSON.stringify(value)) as T;
}

export function findCanvasTarget(
  target: ClosestCapableTarget | null,
):
  | { type: "edge"; edgeId: string | null }
  | { type: "segment"; segmentId: string | null }
  | null {
  const edgeTarget = target?.closest("[data-edge-id]");
  if (edgeTarget) {
    return {
      type: "edge",
      edgeId: edgeTarget.getAttribute("data-edge-id"),
    };
  }

  const segmentTarget = target?.closest("[data-segment-id]");
  if (segmentTarget) {
    return {
      type: "segment",
      segmentId: segmentTarget.getAttribute("data-segment-id"),
    };
  }

  return null;
}

export function haveSameEdgeTopology(
  nextEdges: EditableEdge[] | undefined,
  previousEdges: EditableEdge[] | undefined,
): boolean {
  const nextList = nextEdges ?? [];
  const previousList = previousEdges ?? [];
  if (nextList.length !== previousList.length) {
    return false;
  }

  return nextList.every((edge, index) => {
    const previousEdge = previousList[index];
    return (
      edge.edge_id === previousEdge?.edge_id &&
      edge.left_segment_id === previousEdge?.left_segment_id &&
      edge.right_segment_id === previousEdge?.right_segment_id
    );
  });
}

export function shouldBlockEdgeEditing(input: {
  edgeId: string | null;
  edges: Array<Pick<EditableEdge, "edge_id" | "right_segment_id">>;
  dirtySegmentIds: Iterable<string>;
}): boolean {
  if (!input.edgeId) {
    return false;
  }

  const edge = input.edges.find((item) => item.edge_id === input.edgeId);
  if (!edge) {
    return false;
  }

  const dirtySegmentIds = new Set(input.dirtySegmentIds);
  return dirtySegmentIds.has(edge.right_segment_id);
}

export function shouldPreserveLocalTextDraftsOnVersionChange(input: {
  previousSessionKey: string | null;
  nextSessionKey: string | null;
  isEditing: boolean;
  dirtySegmentIds: Iterable<string>;
  previousSegments: Array<
    Pick<EditableSegment, "segment_id" | "order_key" | "raw_text">
  >;
  nextSegments: Array<Pick<EditableSegment, "segment_id" | "order_key" | "raw_text">>;
  previousEdges: EditableEdge[] | undefined;
  nextEdges: EditableEdge[] | undefined;
}): boolean {
  if (
    !input.previousSessionKey ||
    !input.nextSessionKey ||
    input.previousSessionKey === input.nextSessionKey ||
    input.isEditing
  ) {
    return false;
  }

  if (new Set(input.dirtySegmentIds).size === 0) {
    return false;
  }

  if (
    input.previousSegments.length !== input.nextSegments.length ||
    !haveSameEdgeTopology(input.nextEdges, input.previousEdges)
  ) {
    return false;
  }

  return input.previousSegments.every((previousSegment, index) => {
    const nextSegment = input.nextSegments[index];
    return (
      previousSegment.segment_id === nextSegment?.segment_id &&
      previousSegment.order_key === nextSegment?.order_key &&
      previousSegment.raw_text === nextSegment?.raw_text
    );
  });
}

export function collectPauseBoundaryAttrPatches(input: {
  doc: JSONContent;
  renderMap: WorkspaceRenderMap | null;
  edges: EditableEdge[];
}): Array<{
  from: number;
  attrs: Record<string, unknown>;
}> {
  if (!input.renderMap) {
    return [];
  }

  return input.renderMap.edgeAnchors.flatMap((anchor) => {
    if (!anchor.edgeId) {
      return [];
    }

    const edge = input.edges.find((item) => item.edge_id === anchor.edgeId);
    const node = findNodeAtPosition(input.doc, anchor.from);
    if (!edge || node?.type !== "pauseBoundary") {
      return [];
    }

    const currentPause = node.attrs?.pauseDurationSeconds ?? null;
    const currentStrategy = node.attrs?.boundaryStrategy ?? null;
    if (
      currentPause === edge.pause_duration_seconds &&
      currentStrategy === edge.boundary_strategy
    ) {
      return [];
    }

    return [
      {
        from: anchor.from,
        attrs: {
          ...node.attrs,
          pauseDurationSeconds: edge.pause_duration_seconds,
          boundaryStrategy: edge.boundary_strategy,
        },
      },
    ];
  });
}
