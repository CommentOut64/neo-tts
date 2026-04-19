import type { JSONContent } from "@tiptap/vue-3";
import type { SegmentTextPatch } from "@/types/editSession";

import { buildListLayoutDocument } from "./buildListLayoutDocument";
import type { WorkspaceEditorLayoutMode, WorkspaceSemanticDocument } from "./layoutTypes";
import { buildCompositionLayoutDocument } from "./buildCompositionLayoutDocument";
import {
  extractOrderedSegmentDraftsFromWorkspaceViewDoc,
} from "./sourceDocNormalizer";
import type { WorkspaceSegmentTextDraft } from "./terminalRegionModel";
import { createEmptyWorkspaceSegmentTextDraft } from "./terminalRegionModel";

export interface SegmentEditorParagraph {
  segmentId: string;
  stem: string;
  terminal_raw: string;
  terminal_closer_suffix: string;
  terminal_source: "original" | "synthetic";
}

export interface SegmentDraftChangeSet {
  changedDrafts: Array<[segmentId: string, patch: SegmentTextPatch]>;
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
          text: `${segment.stem}${segment.terminal_source === "synthetic"
            ? segment.terminal_closer_suffix.length > 0
              ? `。${segment.terminal_closer_suffix}`
              : "。"
            : `${segment.terminal_raw}${segment.terminal_closer_suffix}`}`,
          renderStatus: "completed" as const,
          isDirty: false,
        },
      ]),
    ),
    edgesByLeftSegmentId: {},
    sourceBlocks: segments.map((segment, index) => ({
      blockId: `block-${index + 1}`,
      rawLineText: `${segment.stem}${segment.terminal_source === "synthetic"
        ? segment.terminal_closer_suffix.length > 0
          ? `。${segment.terminal_closer_suffix}`
          : "。"
        : `${segment.terminal_raw}${segment.terminal_closer_suffix}`}`,
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
  getBackendDraft: (segmentId: string) => WorkspaceSegmentTextDraft,
): SegmentDraftChangeSet {
  const previousDraftsBySegmentId = Object.fromEntries(
    orderedSegmentIds.map((segmentId) => [segmentId, getBackendDraft(segmentId)]),
  );
  const segmentDrafts = extractOrderedSegmentDraftsFromWorkspaceViewDoc(
    doc,
    orderedSegmentIds,
    previousDraftsBySegmentId,
  );

  const changedDrafts: Array<[segmentId: string, patch: SegmentTextPatch]> = [];
  const clearedSegmentIds: string[] = [];

  segmentDrafts.forEach((draft) => {
    const backendDraft = previousDraftsBySegmentId[draft.segmentId] ??
      createEmptyWorkspaceSegmentTextDraft(draft.segmentId);
    if (
      draft.stem !== backendDraft.stem ||
      draft.terminal_raw !== backendDraft.terminal_raw ||
      draft.terminal_closer_suffix !== backendDraft.terminal_closer_suffix ||
      draft.terminal_source !== backendDraft.terminal_source
    ) {
      changedDrafts.push([
        draft.segmentId,
        {
          stem: draft.stem,
          terminal_raw: draft.terminal_raw,
          terminal_closer_suffix: draft.terminal_closer_suffix,
          terminal_source: draft.terminal_source,
        },
      ]);
      return;
    }

    clearedSegmentIds.push(draft.segmentId);
  });

  return {
    changedDrafts,
    clearedSegmentIds,
  };
}

export function normalizeEditorPastedText(text: string): string {
  return text.replace(/\s*\r?\n+\s*/g, " ").trim();
}
