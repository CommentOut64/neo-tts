import type { JSONContent } from "@tiptap/vue-3";

import type { WorkspaceSourceBlock } from "./layoutTypes";

export interface WorkspaceCompositionLayoutHints {
  basis: "source_text" | "working_copy";
  segmentIdsByBlock: string[][];
  sourceTextStatus: "aligned" | "detached" | "missing";
}

function isRecord(raw: unknown): raw is Record<string, unknown> {
  return raw !== null && typeof raw === "object" && !Array.isArray(raw);
}

export function normalizeCompositionLayoutHints(
  raw: unknown,
): WorkspaceCompositionLayoutHints | null {
  if (raw === null) {
    return null;
  }

  if (!isRecord(raw)) {
    return null;
  }

  if (raw.basis !== "source_text" && raw.basis !== "working_copy") {
    return null;
  }

  if (
    !Array.isArray(raw.segmentIdsByBlock) ||
    !raw.segmentIdsByBlock.every(
      (block) =>
        Array.isArray(block) && block.every((segmentId) => typeof segmentId === "string"),
    )
  ) {
    return null;
  }

  if (
    raw.sourceTextStatus !== "aligned" &&
    raw.sourceTextStatus !== "detached" &&
    raw.sourceTextStatus !== "missing"
  ) {
    return null;
  }

  return {
    basis: raw.basis,
    segmentIdsByBlock: raw.segmentIdsByBlock.map((block) => [...block]),
    sourceTextStatus: raw.sourceTextStatus,
  };
}

export function areCompositionLayoutHintsCompatible(
  hints: WorkspaceCompositionLayoutHints | null,
  segmentOrder: string[],
): boolean {
  if (!hints) {
    return false;
  }

  const flattened = hints.segmentIdsByBlock.flat();
  if (flattened.length !== segmentOrder.length) {
    return false;
  }

  return flattened.every((segmentId, index) => segmentId === segmentOrder[index]);
}

export function buildCompositionLayoutHintsFromSourceBlocks(input: {
  sourceBlocks: WorkspaceSourceBlock[];
  basis: WorkspaceCompositionLayoutHints["basis"];
  sourceTextStatus: WorkspaceCompositionLayoutHints["sourceTextStatus"];
}): WorkspaceCompositionLayoutHints {
  return {
    basis: input.basis,
    segmentIdsByBlock: input.sourceBlocks.map((block) => [...block.segmentIds]),
    sourceTextStatus: input.sourceTextStatus,
  };
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

function collectParagraphSegmentIds(node: JSONContent): string[] {
  const segmentIds: string[] = [];
  const seenSegmentIds = new Set<string>();

  const visit = (currentNode: JSONContent | undefined) => {
    if (!currentNode) {
      return;
    }

    if (typeof currentNode.text === "string") {
      const segmentId = readSegmentAnchorId(currentNode);
      if (segmentId && !seenSegmentIds.has(segmentId)) {
        seenSegmentIds.add(segmentId);
        segmentIds.push(segmentId);
      }
      return;
    }

    currentNode.content?.forEach(visit);
  };

  visit(node);
  return segmentIds;
}

export function buildCompositionLayoutHintsFromViewDoc(input: {
  viewDoc: JSONContent;
  basis: WorkspaceCompositionLayoutHints["basis"];
  sourceTextStatus: WorkspaceCompositionLayoutHints["sourceTextStatus"];
}): WorkspaceCompositionLayoutHints {
  const segmentIdsByBlock = (input.viewDoc.content ?? [])
    .filter((node) => node.type === "paragraph")
    .map((node) => collectParagraphSegmentIds(node))
    .filter((block) => block.length > 0);

  return {
    basis: input.basis,
    segmentIdsByBlock,
    sourceTextStatus: input.sourceTextStatus,
  };
}
