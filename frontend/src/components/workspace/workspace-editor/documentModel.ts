import type { JSONContent } from "@tiptap/vue-3";

import { buildListLayoutDocument } from "./buildListLayoutDocument";
import type { WorkspaceEditorLayoutMode, WorkspaceSemanticDocument } from "./layoutTypes";
import { buildCompositionLayoutDocument } from "./buildCompositionLayoutDocument";
import { extractOrderedSegmentTextsFromWorkspaceViewDoc } from "./sourceDocNormalizer";

export interface SegmentEditorParagraph {
  segmentId: string;
  text: string;
}

export interface SegmentDraftChangeSet {
  changedDrafts: Array<[segmentId: string, text: string]>;
  clearedSegmentIds: string[];
}

export function buildSegmentEditorDocument(
  segments: SegmentEditorParagraph[],
): JSONContent {
  return buildListLayoutDocument({
    segmentOrder: segments.map((segment) => segment.segmentId),
    segmentsById: Object.fromEntries(
      segments.map((segment, index) => [
        segment.segmentId,
        {
          segmentId: segment.segmentId,
          orderKey: index + 1,
          text: segment.text,
          renderStatus: "completed" as const,
          isDirty: false,
        },
      ]),
    ),
    edgesByLeftSegmentId: {},
    sourceBlocks: segments.map((segment, index) => ({
      blockId: `block-${index + 1}`,
      rawLineText: segment.text,
      segmentIds: [segment.segmentId],
    })),
    compositionAvailability: {
      ready: false,
      reason: "missing_source_text",
    },
  }).doc;
}

export function buildWorkspaceRenderPlan(
  semanticDocument: WorkspaceSemanticDocument,
  layoutMode: WorkspaceEditorLayoutMode,
) {
  return layoutMode === "composition"
    ? buildCompositionLayoutDocument(semanticDocument)
    : buildListLayoutDocument(semanticDocument);
}

export function collectSegmentDraftChanges(
  doc: JSONContent,
  orderedSegmentIds: string[],
  getBackendText: (segmentId: string) => string,
): SegmentDraftChangeSet {
  const segmentTexts = extractOrderedSegmentTextsFromWorkspaceViewDoc(
    doc,
    orderedSegmentIds,
  );

  const changedDrafts: Array<[segmentId: string, text: string]> = [];
  const clearedSegmentIds: string[] = [];

  segmentTexts.forEach(({ segmentId, text }) => {
    const backendText = getBackendText(segmentId);

    if (text !== backendText) {
      changedDrafts.push([segmentId, text]);
      return;
    }

    clearedSegmentIds.push(segmentId);
  });

  return {
    changedDrafts,
    clearedSegmentIds,
  };
}

export function normalizeEditorPastedText(text: string): string {
  return text.replace(/\s*\r?\n+\s*/g, " ").trim();
}
