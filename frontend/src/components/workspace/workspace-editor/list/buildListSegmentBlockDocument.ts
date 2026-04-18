import type {
  WorkspaceRenderPlan,
  WorkspaceSemanticDocument,
} from "../layoutTypes";
import { buildWorkspaceSegmentTextNodesFromDisplayText } from "../terminalRegionModel";

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

export function buildListSegmentBlockDocument(
  semanticDocument: WorkspaceSemanticDocument,
): WorkspaceRenderPlan {
  const content =
    semanticDocument.segmentOrder.length > 0
      ? semanticDocument.segmentOrder.map((segmentId) => {
          const segment = semanticDocument.segmentsById[segmentId];
          const segmentContent: Array<Record<string, unknown>> = [];
          const renderedText =
            segment?.renderStatus === "completed" ? segment.text : "";

          if (renderedText) {
            segmentContent.push(
              ...buildWorkspaceSegmentTextNodesFromDisplayText({
                segmentId,
                text: renderedText,
              }),
            );
          }

          const pauseBoundaryNode = buildPauseBoundaryNode(
            semanticDocument,
            segmentId,
          );
          if (pauseBoundaryNode) {
            segmentContent.push(pauseBoundaryNode);
          }

          return {
            type: "segmentBlock",
            attrs: {
              segmentId,
            },
            content: segmentContent,
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
      edgeAnchors: [],
    },
  };
}
