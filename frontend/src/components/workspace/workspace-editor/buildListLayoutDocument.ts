import type {
  WorkspaceRenderPlan,
  WorkspaceSemanticDocument,
} from "./layoutTypes";

function buildSegmentTextNode(segmentId: string, text: string) {
  return {
    type: "text",
    text,
    marks: [{ type: "segmentAnchor", attrs: { segmentId } }],
  };
}

function buildPauseBoundaryNode(
  semanticDocument: WorkspaceSemanticDocument,
  leftSegmentId: string,
) {
  const edge = semanticDocument.edgesByLeftSegmentId[leftSegmentId];
  if (!edge) {
    return null;
  }

  return {
    type: "pauseBoundary",
    attrs: {
      edgeId: edge.edgeId,
      leftSegmentId: edge.leftSegmentId,
      rightSegmentId: edge.rightSegmentId,
      pauseDurationSeconds: edge.pauseDurationSeconds,
      boundaryStrategy: edge.boundaryStrategy,
      layoutMode: "list" as const,
      crossBlock: false,
    },
  };
}

export function buildListLayoutDocument(
  semanticDocument: WorkspaceSemanticDocument,
): WorkspaceRenderPlan {
  const content =
    semanticDocument.segmentOrder.length > 0
      ? semanticDocument.segmentOrder.map((segmentId) => {
          const segment = semanticDocument.segmentsById[segmentId];
          const paragraphContent: Array<Record<string, unknown>> = [];
          const renderedText =
            segment?.renderStatus === "completed" ? segment.text : "";

          if (renderedText) {
            paragraphContent.push(buildSegmentTextNode(segmentId, renderedText));
          }

          const pauseBoundaryNode = buildPauseBoundaryNode(
            semanticDocument,
            segmentId,
          );
          if (pauseBoundaryNode) {
            paragraphContent.push(pauseBoundaryNode);
          }

          return {
            type: "paragraph",
            content: paragraphContent,
          };
        })
      : [{ type: "paragraph", content: [] }];

  return {
    layoutMode: "list",
    doc: {
      type: "doc",
      content,
    },
    renderMap: {
      orderedSegmentIds: [...semanticDocument.segmentOrder],
      segmentRanges: [],
      segmentBlockRanges: [],
      edgeAnchors: [],
    },
  };
}
