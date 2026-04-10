import type { JSONContent } from "@tiptap/vue-3";

import type { WorkspaceEditorLayoutMode, WorkspaceRenderMap } from "./layoutTypes";

interface WalkContext {
  position: number;
}

function getNodeSize(node: JSONContent): number {
  if (typeof node.text === "string") {
    return node.text.length;
  }

  if (!node.content || node.content.length === 0) {
    return 1;
  }

  if (node.type === "doc") {
    return node.content.reduce((total, child) => total + getNodeSize(child), 0);
  }

  return 2 + node.content.reduce((total, child) => total + getNodeSize(child), 0);
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

function walkDoc(
  node: JSONContent,
  context: WalkContext,
  visit: (currentNode: JSONContent, from: number, to: number) => void,
) {
  if (typeof node.text === "string") {
    const from = context.position;
    const to = from + node.text.length;
    visit(node, from, to);
    context.position = to;
    return;
  }

  const from = context.position;
  if (!node.content || node.content.length === 0) {
    const to = from + 1;
    visit(node, from, to);
    context.position = to;
    return;
  }

  visit(node, from, from + getNodeSize(node));
  if (node.type === "doc") {
    for (const child of node.content) {
      walkDoc(child, context, visit);
    }
    return;
  }

  context.position += 1;
  for (const child of node.content) {
    walkDoc(child, context, visit);
  }
  context.position += 1;
}

export function findNodeAtPosition(
  doc: JSONContent,
  targetFrom: number,
): JSONContent | null {
  let match: JSONContent | null = null;
  walkDoc(doc, { position: 0 }, (node, from) => {
    if (match === null && from === targetFrom) {
      match = node;
    }
  });
  return match;
}

export function extractRenderMapFromDoc(
  doc: JSONContent,
  orderedSegmentIds: string[],
  layoutMode: WorkspaceEditorLayoutMode = "composition",
): WorkspaceRenderMap {
  const segmentRanges: WorkspaceRenderMap["segmentRanges"] = [];
  const edgeAnchors: WorkspaceRenderMap["edgeAnchors"] = [];

  walkDoc(doc, { position: 0 }, (node, from, to) => {
    if (typeof node.text === "string") {
      const segmentId = readSegmentAnchorId(node);
      if (segmentId) {
        segmentRanges.push({
          segmentId,
          from,
          to,
        });
      }
      return;
    }

    if (node.type === "pauseBoundary") {
      edgeAnchors.push({
        edgeId:
          typeof node.attrs?.edgeId === "string" ? node.attrs.edgeId : null,
        leftSegmentId: String(node.attrs?.leftSegmentId ?? ""),
        rightSegmentId: String(node.attrs?.rightSegmentId ?? ""),
        from,
        to,
        layoutMode:
          node.attrs?.layoutMode === "composition" ? "composition" : "list",
        crossBlock: Boolean(node.attrs?.crossBlock),
      });
    }
  });

  return {
    orderedSegmentIds: [...orderedSegmentIds],
    segmentRanges,
    edgeAnchors,
  };
}
