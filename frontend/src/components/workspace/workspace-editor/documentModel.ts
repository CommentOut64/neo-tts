import type { JSONContent } from "@tiptap/vue-3";

import { buildListLayoutDocument } from "./buildListLayoutDocument";
import type { WorkspaceEditorLayoutMode, WorkspaceSemanticDocument } from "./layoutTypes";
import { buildCompositionLayoutDocument } from "./buildCompositionLayoutDocument";

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
  const textBySegmentId = new Map<string, string>();
  const seenSegmentIds: string[] = [];
  let currentSegmentId: string | null = null;
  let sawPauseBoundarySinceLastSegment = true;
  let encounteredSegmentAnchor = false;

  walkDocument(doc, (node) => {
    if (node.type === "pauseBoundary") {
      if (currentSegmentId !== null) {
        sawPauseBoundarySinceLastSegment = true;
      }
      return;
    }

    if (typeof node.text !== "string" || node.text.length === 0) {
      return;
    }

    const segmentId = readSegmentAnchorId(node);
    if (!segmentId) {
      throw new Error("编辑器 segmentAnchor 已变化，请放弃当前编辑后重试");
    }

    encounteredSegmentAnchor = true;
    if (currentSegmentId !== segmentId) {
      if (currentSegmentId !== null && !sawPauseBoundarySinceLastSegment) {
        throw new Error("编辑器 pauseBoundary 已变化，请放弃当前编辑后重试");
      }
      if (textBySegmentId.has(segmentId)) {
        throw new Error("编辑器 segmentAnchor 已变化，请放弃当前编辑后重试");
      }
      seenSegmentIds.push(segmentId);
      currentSegmentId = segmentId;
      sawPauseBoundarySinceLastSegment = false;
    }

    textBySegmentId.set(
      segmentId,
      `${textBySegmentId.get(segmentId) ?? ""}${node.text}`,
    );
  });

  if (!encounteredSegmentAnchor) {
    throw new Error("编辑器 segmentAnchor 已变化，请放弃当前编辑后重试");
  }

  if (seenSegmentIds.length !== orderedSegmentIds.length) {
    throw new Error("编辑器段落结构已变化，请放弃当前编辑后重试");
  }

  orderedSegmentIds.forEach((segmentId, index) => {
    if (seenSegmentIds[index] !== segmentId) {
      throw new Error("编辑器段落结构已变化，请放弃当前编辑后重试");
    }
  });

  const changedDrafts: Array<[segmentId: string, text: string]> = [];
  const clearedSegmentIds: string[] = [];

  orderedSegmentIds.forEach((segmentId) => {
    const currentText = textBySegmentId.get(segmentId) ?? "";
    const backendText = getBackendText(segmentId);

    if (currentText !== backendText) {
      changedDrafts.push([segmentId, currentText]);
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

function walkDocument(
  node: JSONContent | undefined,
  visit: (currentNode: JSONContent) => void,
) {
  if (!node) {
    return;
  }

  visit(node);

  for (const child of node.content ?? []) {
    walkDocument(child, visit);
  }
}

function readSegmentAnchorId(node: JSONContent): string | null {
  const anchorMark = (node.marks ?? []).find(
    (mark) => mark.type === "segmentAnchor",
  );
  const segmentId = anchorMark?.attrs?.segmentId;
  return typeof segmentId === "string" && segmentId.length > 0
    ? segmentId
    : null;
}
