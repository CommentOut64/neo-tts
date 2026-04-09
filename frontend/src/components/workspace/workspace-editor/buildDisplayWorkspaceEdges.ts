import type { WorkspaceSemanticEdge } from "./layoutTypes";

export const DEFAULT_REORDER_PAUSE_DURATION_SECONDS = 0.3;
export const DEFAULT_REORDER_BOUNDARY_STRATEGY =
  "latent_overlap_then_equal_power_crossfade";

function buildEdgePairKey(leftSegmentId: string, rightSegmentId: string) {
  return `${leftSegmentId}::${rightSegmentId}`;
}

export function buildDisplayWorkspaceEdges(input: {
  orderedSegmentIds: string[];
  edges: WorkspaceSemanticEdge[];
}): WorkspaceSemanticEdge[] {
  if (input.orderedSegmentIds.length <= 1) {
    return [];
  }

  const edgeByPairKey = new Map<string, WorkspaceSemanticEdge>(
    input.edges.map((edge) => [
      buildEdgePairKey(edge.leftSegmentId, edge.rightSegmentId),
      edge,
    ]),
  );

  return input.orderedSegmentIds.slice(0, -1).map((leftSegmentId, index) => {
    const rightSegmentId = input.orderedSegmentIds[index + 1];
    const reusedEdge = edgeByPairKey.get(
      buildEdgePairKey(leftSegmentId, rightSegmentId),
    );

    if (reusedEdge) {
      return {
        edgeId: reusedEdge.edgeId,
        leftSegmentId: reusedEdge.leftSegmentId,
        rightSegmentId: reusedEdge.rightSegmentId,
        pauseDurationSeconds: reusedEdge.pauseDurationSeconds,
        boundaryStrategy: reusedEdge.boundaryStrategy,
      };
    }

    return {
      edgeId: null,
      leftSegmentId,
      rightSegmentId,
      pauseDurationSeconds: DEFAULT_REORDER_PAUSE_DURATION_SECONDS,
      boundaryStrategy: DEFAULT_REORDER_BOUNDARY_STRATEGY,
    };
  });
}
