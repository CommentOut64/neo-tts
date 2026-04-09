import type { JSONContent } from "@tiptap/vue-3";

import {
  extractOrderedSegmentTextsFromListViewDoc,
  normalizeListViewDocToSourceDoc,
} from "./list/normalizeListViewDocToSourceDoc";
import type { WorkspaceSemanticEdge } from "./layoutTypes";
import { buildWorkspaceSourceDoc } from "./sourceDocModel";

export interface WorkspaceSourceDocTextEntry {
  segmentId: string;
  text: string;
}

export interface NormalizeWorkspaceViewDocInput {
  viewDoc: JSONContent;
  orderedSegmentIds: string[];
  edges: WorkspaceSemanticEdge[];
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

function isListViewDoc(doc: JSONContent): boolean {
  return (doc.content ?? []).some((node) => node.type === "segmentBlock");
}

export function extractOrderedSegmentTextsFromWorkspaceViewDoc(
  doc: JSONContent,
  orderedSegmentIds: string[],
): WorkspaceSourceDocTextEntry[] {
  if (isListViewDoc(doc)) {
    return extractOrderedSegmentTextsFromListViewDoc(doc, orderedSegmentIds);
  }

  if (orderedSegmentIds.length === 0) {
    return [];
  }

  const textBySegmentId = new Map<string, string>();
  const seenSegmentIds: string[] = [];
  let currentSegmentId: string | null = null;
  let sawPauseBoundarySinceLastSegment = true;
  let encounteredSegmentAnchor = false;
  let pendingTextForNextSegment = "";

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
      if (currentSegmentId !== null && !sawPauseBoundarySinceLastSegment) {
        textBySegmentId.set(
          currentSegmentId,
          `${textBySegmentId.get(currentSegmentId) ?? ""}${node.text}`,
        );
        return;
      }

      pendingTextForNextSegment += node.text;
      return;
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

    if (pendingTextForNextSegment.length > 0) {
      textBySegmentId.set(
        segmentId,
        `${textBySegmentId.get(segmentId) ?? ""}${pendingTextForNextSegment}`,
      );
      pendingTextForNextSegment = "";
    }

    textBySegmentId.set(
      segmentId,
      `${textBySegmentId.get(segmentId) ?? ""}${node.text}`,
    );
  });

  if (!encounteredSegmentAnchor) {
    throw new Error("编辑器 segmentAnchor 已变化，请放弃当前编辑后重试");
  }

  if (pendingTextForNextSegment.length > 0) {
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

  return orderedSegmentIds.map((segmentId) => ({
    segmentId,
    text: textBySegmentId.get(segmentId) ?? "",
  }));
}

export function normalizeWorkspaceViewDocToSourceDoc(
  input: NormalizeWorkspaceViewDocInput,
): JSONContent {
  if (isListViewDoc(input.viewDoc)) {
    return normalizeListViewDocToSourceDoc(input);
  }

  const segmentTexts = extractOrderedSegmentTextsFromWorkspaceViewDoc(
    input.viewDoc,
    input.orderedSegmentIds,
  );

  return buildWorkspaceSourceDoc({
    segments: segmentTexts.map((segment, index) => ({
      segmentId: segment.segmentId,
      orderKey: index + 1,
      text: segment.text,
    })),
    edges: input.edges,
  });
}
