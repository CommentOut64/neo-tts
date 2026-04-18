import type { JSONContent } from "@tiptap/vue-3";
import type { ResolvedLanguage } from "@/types/editSession";

import { buildListLayoutDocument } from "./buildListLayoutDocument";
import type { WorkspaceSemanticEdge, WorkspaceSemanticDocument } from "./layoutTypes";
import { buildWorkspaceSegmentDisplayTextFromDraft } from "./terminalRegionModel";

export type WorkspaceSourceDoc = JSONContent;

export interface WorkspaceSourceDocSegmentInput {
  segmentId: string;
  orderKey: number;
  stem: string;
  terminal_raw: string;
  terminal_closer_suffix: string;
  terminal_source: "original" | "synthetic";
  detectedLanguage?: ResolvedLanguage | null;
  textLanguage?: string | null;
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
          text: buildWorkspaceSegmentDisplayTextFromDraft({
            draft: {
              segmentId: segment.segmentId,
              stem: segment.stem,
              terminal_raw: segment.terminal_raw,
              terminal_closer_suffix: segment.terminal_closer_suffix,
              terminal_source: segment.terminal_source,
            },
            detectedLanguage: segment.detectedLanguage,
            textLanguage: segment.textLanguage,
          }),
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
      rawLineText: buildWorkspaceSegmentDisplayTextFromDraft({
        draft: {
          segmentId: segment.segmentId,
          stem: segment.stem,
          terminal_raw: segment.terminal_raw,
          terminal_closer_suffix: segment.terminal_closer_suffix,
          terminal_source: segment.terminal_source,
        },
        detectedLanguage: segment.detectedLanguage,
        textLanguage: segment.textLanguage,
      }),
      segmentIds: [segment.segmentId],
    })),
    compositionAvailability: {
      ready: false,
      reason: "canonical_source_doc",
    },
  };

  return buildListLayoutDocument(semanticDocument).doc;
}
