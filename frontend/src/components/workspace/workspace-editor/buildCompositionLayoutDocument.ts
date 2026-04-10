import { buildListLayoutDocument } from "./buildListLayoutDocument";
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
  crossBlock: boolean,
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
      layoutMode: "composition" as const,
      crossBlock,
    },
  };
}

function findNextBlockFirstSegmentId(
  semanticDocument: WorkspaceSemanticDocument,
  currentBlockIndex: number,
): string | null {
  for (
    let index = currentBlockIndex + 1;
    index < semanticDocument.sourceBlocks.length;
    index += 1
  ) {
    const nextSegmentId = semanticDocument.sourceBlocks[index]?.segmentIds[0];
    if (nextSegmentId) {
      return nextSegmentId;
    }
  }

  return null;
}

export function buildCompositionLayoutDocument(
  semanticDocument: WorkspaceSemanticDocument,
): WorkspaceRenderPlan {
  if (
    !semanticDocument.compositionAvailability.ready ||
    semanticDocument.sourceBlocks.length === 0
  ) {
    const fallback = buildListLayoutDocument(semanticDocument);
    return {
      ...fallback,
      layoutMode: "composition",
    };
  }

  return {
    layoutMode: "composition",
    doc: {
      type: "doc",
      content: semanticDocument.sourceBlocks.map((block, blockIndex) => {
        const paragraphContent: Array<Record<string, unknown>> = [];

        block.segmentIds.forEach((segmentId, segmentIndex) => {
          const segment = semanticDocument.segmentsById[segmentId];
          if (!segment) {
            return;
          }

          const renderedText =
            segment.renderStatus === "completed" ? segment.text : "";
          if (renderedText) {
            paragraphContent.push(buildSegmentTextNode(segmentId, renderedText));
          }

          const isLastSegmentInBlock = segmentIndex === block.segmentIds.length - 1;
          if (!isLastSegmentInBlock) {
            const inlineBoundary = buildPauseBoundaryNode(
              semanticDocument,
              segmentId,
              false,
            );
            if (inlineBoundary) {
              paragraphContent.push(inlineBoundary);
            }
            return;
          }

          const nextBlockFirstSegmentId = findNextBlockFirstSegmentId(
            semanticDocument,
            blockIndex,
          );
          const crossBlockBoundary = buildPauseBoundaryNode(
            semanticDocument,
            segmentId,
            nextBlockFirstSegmentId ===
              semanticDocument.edgesByLeftSegmentId[segmentId]?.rightSegmentId,
          );
          if (crossBlockBoundary && nextBlockFirstSegmentId) {
            paragraphContent.push(crossBlockBoundary);
          }
        });

        return {
          type: "paragraph",
          content: paragraphContent,
        };
      }),
    },
    renderMap: {
      orderedSegmentIds: [...semanticDocument.segmentOrder],
      segmentRanges: [],
      edgeAnchors: [],
    },
  };
}
