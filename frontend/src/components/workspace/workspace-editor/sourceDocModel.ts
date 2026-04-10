import type { JSONContent } from "@tiptap/vue-3";

import { buildListLayoutDocument } from "./buildListLayoutDocument";
import type { WorkspaceSemanticEdge, WorkspaceSemanticDocument } from "./layoutTypes";

export type WorkspaceSourceDoc = JSONContent;

export interface WorkspaceSourceDocSegmentInput {
  segmentId: string;
  orderKey: number;
  text: string;
}

export interface BuildWorkspaceSourceDocInput {
  segments: WorkspaceSourceDocSegmentInput[];
  edges?: WorkspaceSemanticEdge[];
}

export function createEmptyWorkspaceSourceDoc(): WorkspaceSourceDoc {
  return {
    type: "doc",
    content: [{ type: "paragraph", content: [] }],
  };
}

export function buildWorkspaceSourceDoc(
  input: BuildWorkspaceSourceDocInput,
): WorkspaceSourceDoc {
  const semanticDocument: WorkspaceSemanticDocument = {
    segmentOrder: input.segments.map((segment) => segment.segmentId),
    segmentsById: Object.fromEntries(
      input.segments.map((segment) => [
        segment.segmentId,
        {
          segmentId: segment.segmentId,
          orderKey: segment.orderKey,
          text: segment.text,
          renderStatus: "completed" as const,
          isDirty: false,
        },
      ]),
    ),
    edgesByLeftSegmentId: Object.fromEntries(
      (input.edges ?? []).map((edge) => [
        edge.leftSegmentId,
        {
          edgeId: edge.edgeId,
          leftSegmentId: edge.leftSegmentId,
          rightSegmentId: edge.rightSegmentId,
          pauseDurationSeconds: edge.pauseDurationSeconds,
          boundaryStrategy: edge.boundaryStrategy,
        },
      ]),
    ),
    sourceBlocks: input.segments.map((segment, index) => ({
      blockId: `canonical-block-${index + 1}`,
      rawLineText: segment.text,
      segmentIds: [segment.segmentId],
    })),
    compositionAvailability: {
      ready: false,
      reason: "canonical_source_doc",
    },
  };

  return buildListLayoutDocument(semanticDocument).doc;
}
