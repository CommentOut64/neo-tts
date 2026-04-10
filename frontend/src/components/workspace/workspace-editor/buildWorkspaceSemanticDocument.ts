import type {
  BuildWorkspaceSemanticDocumentInput,
  WorkspaceSemanticDocument,
  WorkspaceSemanticEdge,
  WorkspaceSemanticSegment,
  WorkspaceSourceBlock,
} from "./layoutTypes";
import { areCompositionLayoutHintsCompatible } from "./compositionLayoutHints";

function normalizeAlignmentText(text: string): string {
  return text.replace(/\r/g, "").trim();
}

function splitSourceLines(sourceText: string): string[] {
  return sourceText.replace(/\r\n/g, "\n").split("\n");
}

function buildSourceBlocksFromHints(
  segmentIdsByBlock: string[][],
  segmentsById: Record<string, WorkspaceSemanticSegment>,
): WorkspaceSourceBlock[] {
  return segmentIdsByBlock.map((segmentIds, index) => ({
    blockId: `hint-block-${index + 1}`,
    rawLineText: segmentIds.map((segmentId) => segmentsById[segmentId]?.text ?? "").join(""),
    segmentIds: [...segmentIds],
  }));
}

function buildWorkingCopyBlocks(
  segmentOrder: string[],
  segmentsById: Record<string, WorkspaceSemanticSegment>,
): WorkspaceSourceBlock[] {
  if (segmentOrder.length === 0) {
    return [];
  }

  return [
    {
      blockId: "working-copy-block-1",
      rawLineText: segmentOrder.map((segmentId) => segmentsById[segmentId]?.text ?? "").join(""),
      segmentIds: [...segmentOrder],
    },
  ];
}

function resolveSourceBlocks(
  sourceText: string | null,
  compositionLayoutHints: BuildWorkspaceSemanticDocumentInput["compositionLayoutHints"],
  segmentOrder: string[],
  segmentsById: Record<string, WorkspaceSemanticSegment>,
): {
  sourceBlocks: WorkspaceSourceBlock[];
  ready: boolean;
  reason: string | null;
} {
  if (
    compositionLayoutHints &&
    areCompositionLayoutHintsCompatible(compositionLayoutHints, segmentOrder)
  ) {
    return {
      sourceBlocks: buildSourceBlocksFromHints(
        compositionLayoutHints.segmentIdsByBlock,
        segmentsById,
      ),
      ready: true,
      reason:
        compositionLayoutHints.sourceTextStatus === "detached"
          ? "detached_hints"
          : compositionLayoutHints.sourceTextStatus === "missing"
            ? "missing_source_text"
            : null,
    };
  }

  if (!sourceText) {
    return {
      sourceBlocks: buildWorkingCopyBlocks(segmentOrder, segmentsById),
      ready: segmentOrder.length > 0,
      reason: "missing_source_text",
    };
  }

  const sourceBlocks: WorkspaceSourceBlock[] = [];
  const sourceLines = splitSourceLines(sourceText);
  let segmentCursor = 0;

  for (const [index, rawLineText] of sourceLines.entries()) {
    const normalizedLineText = normalizeAlignmentText(rawLineText);
    if (normalizedLineText.length === 0) {
      sourceBlocks.push({
        blockId: `block-${index + 1}`,
        rawLineText,
        segmentIds: [],
      });
      continue;
    }

    const blockSegmentIds: string[] = [];
    let buffer = "";

    while (segmentCursor < segmentOrder.length) {
      const segmentId = segmentOrder[segmentCursor];
      const segment = segmentsById[segmentId];
      if (!segment) {
        return {
          sourceBlocks: buildWorkingCopyBlocks(segmentOrder, segmentsById),
          ready: segmentOrder.length > 0,
          reason: "source_text_mismatch",
        };
      }

      buffer += normalizeAlignmentText(segment.text);
      blockSegmentIds.push(segmentId);
      segmentCursor += 1;

      if (buffer === normalizedLineText) {
        break;
      }

      if (!normalizedLineText.startsWith(buffer)) {
        return {
          sourceBlocks: buildWorkingCopyBlocks(segmentOrder, segmentsById),
          ready: segmentOrder.length > 0,
          reason: "source_text_mismatch",
        };
      }
    }

    if (buffer !== normalizedLineText) {
      return {
        sourceBlocks: buildWorkingCopyBlocks(segmentOrder, segmentsById),
        ready: segmentOrder.length > 0,
        reason: "source_text_mismatch",
      };
    }

    sourceBlocks.push({
      blockId: `block-${index + 1}`,
      rawLineText,
      segmentIds: blockSegmentIds,
    });
  }

  if (segmentCursor !== segmentOrder.length) {
    return {
      sourceBlocks: buildWorkingCopyBlocks(segmentOrder, segmentsById),
      ready: segmentOrder.length > 0,
      reason: "source_text_mismatch",
    };
  }

  return {
    sourceBlocks,
    ready: true,
    reason: null,
  };
}

export function buildWorkspaceSemanticDocument(
  input: BuildWorkspaceSemanticDocumentInput,
): WorkspaceSemanticDocument {
  const sortedSegments = [...input.segments].sort(
    (left, right) => left.orderKey - right.orderKey,
  );
  const segmentOrder = sortedSegments.map((segment) => segment.segmentId);
  const dirtySegmentIds = input.dirtySegmentIds ?? new Set<string>();

  const segmentsById = sortedSegments.reduce<Record<string, WorkspaceSemanticSegment>>(
    (accumulator, segment) => {
      accumulator[segment.segmentId] = {
        segmentId: segment.segmentId,
        orderKey: segment.orderKey,
        text: segment.text,
        renderStatus: segment.renderStatus,
        isDirty: dirtySegmentIds.has(segment.segmentId),
      };
      return accumulator;
    },
    {},
  );

  const edgesByLeftSegmentId = (input.edges ?? []).reduce<
    Record<string, WorkspaceSemanticEdge>
  >((accumulator, edge) => {
    accumulator[edge.leftSegmentId] = {
      edgeId: edge.edgeId,
      leftSegmentId: edge.leftSegmentId,
      rightSegmentId: edge.rightSegmentId,
      pauseDurationSeconds: edge.pauseDurationSeconds,
      boundaryStrategy: edge.boundaryStrategy,
    };
    return accumulator;
  }, {});

  const sourceBlockResult = resolveSourceBlocks(
    input.sourceText,
    input.compositionLayoutHints ?? null,
    segmentOrder,
    segmentsById,
  );

  return {
    segmentOrder,
    segmentsById,
    edgesByLeftSegmentId,
    sourceBlocks: sourceBlockResult.sourceBlocks,
    compositionAvailability: {
      ready: sourceBlockResult.ready,
      reason: sourceBlockResult.reason,
    },
  };
}
