import type { JSONContent } from "@tiptap/vue-3";

import type { WorkspaceSemanticEdge } from "../layoutTypes";
import { buildWorkspaceSourceDoc } from "../sourceDocModel";
import type { WorkspaceSourceDocTextEntry } from "../sourceDocNormalizer";

export interface NormalizeListViewDocInput {
  viewDoc: JSONContent;
  orderedSegmentIds: string[];
  edges: WorkspaceSemanticEdge[];
}

function readSegmentBlockId(node: JSONContent): string | null {
  const segmentId = node.attrs?.segmentId;
  return typeof segmentId === "string" && segmentId.length > 0
    ? segmentId
    : null;
}

function collectPlainText(node: JSONContent | undefined): string {
  if (!node) {
    return "";
  }

  if (typeof node.text === "string") {
    return node.text;
  }

  if (!node.content || node.content.length === 0) {
    return "";
  }

  return node.content
    .filter((child) => child.type !== "pauseBoundary")
    .map((child) => collectPlainText(child))
    .join("");
}

export function extractOrderedSegmentTextsFromListViewDoc(
  doc: JSONContent,
  orderedSegmentIds: string[],
): WorkspaceSourceDocTextEntry[] {
  if (orderedSegmentIds.length === 0) {
    return [];
  }

  const segmentBlocks = (doc.content ?? []).filter(
    (node) => node.type === "segmentBlock",
  );
  if (segmentBlocks.length !== orderedSegmentIds.length) {
    throw new Error("编辑器段落结构已变化，请放弃当前编辑后重试");
  }

  const seenSegmentIds = new Set<string>();

  return segmentBlocks.map((node, index) => {
    const segmentId = readSegmentBlockId(node);
    if (!segmentId) {
      throw new Error("编辑器 segmentId 已变化，请放弃当前编辑后重试");
    }
    if (seenSegmentIds.has(segmentId)) {
      throw new Error("编辑器 segmentId 已变化，请放弃当前编辑后重试");
    }
    if (orderedSegmentIds[index] !== segmentId) {
      throw new Error("编辑器 segmentId 已变化，请放弃当前编辑后重试");
    }

    seenSegmentIds.add(segmentId);
    return {
      segmentId,
      text: collectPlainText(node),
    };
  });
}

export function normalizeListViewDocToSourceDoc(
  input: NormalizeListViewDocInput,
): JSONContent {
  const segmentTexts = extractOrderedSegmentTextsFromListViewDoc(
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
