import type { JSONContent } from "@tiptap/vue-3";

import type { EditableEdge } from "@/types/editSession";

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
