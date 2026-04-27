export interface ParameterPanelScopeContext {
  scope: "session" | "segment" | "batch" | "edge";
  segmentIds: string[];
  edgeId: string | null;
}

export function resolveParameterScope(input: {
  selectedSegmentIds: Set<string>;
  selectedEdgeId: string | null;
}): ParameterPanelScopeContext {
  if (input.selectedEdgeId) {
    return {
      scope: "edge",
      segmentIds: [],
      edgeId: input.selectedEdgeId,
    };
  }

  const segmentIds = Array.from(input.selectedSegmentIds);
  if (segmentIds.length === 0) {
    return {
      scope: "session",
      segmentIds: [],
      edgeId: null,
    };
  }

  if (segmentIds.length === 1) {
    return {
      scope: "segment",
      segmentIds,
      edgeId: null,
    };
  }

  return {
    scope: "batch",
    segmentIds,
    edgeId: null,
  };
}

export function shouldConfirmGlobalParameterSubmit(
  context: ParameterPanelScopeContext,
): boolean {
  return (
    context.scope === "session" &&
    context.segmentIds.length === 0 &&
    context.edgeId === null
  );
}
