import type { JSONContent } from "@tiptap/vue-3";

import {
  extractOrderedSegmentDraftsFromListViewDoc,
  normalizeListViewDocToSourceDoc,
} from "./list/normalizeListViewDocToSourceDoc";
import type { WorkspaceSemanticEdge } from "./layoutTypes";
import { buildWorkspaceSourceDoc } from "./sourceDocModel";
import {
  createEmptyWorkspaceSegmentTextDraft,
  resolveWorkspaceSegmentDraftFromRegions,
  type WorkspaceSegmentTextDraft,
} from "./terminalRegionModel";

export interface NormalizeWorkspaceViewDocInput {
  viewDoc: JSONContent;
  orderedSegmentIds: string[];
  edges: WorkspaceSemanticEdge[];
  previousDraftsBySegmentId?: Record<string, WorkspaceSegmentTextDraft>;
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

function hasTerminalCapsuleMark(node: JSONContent): boolean {
  return (node.marks ?? []).some((mark) => mark.type === "terminalCapsule");
}

function isListViewDoc(doc: JSONContent): boolean {
  return (doc.content ?? []).some((node) => node.type === "segmentBlock");
}

export function extractOrderedSegmentDraftsFromWorkspaceViewDoc(
  doc: JSONContent,
  orderedSegmentIds: string[],
  previousDraftsBySegmentId: Record<string, WorkspaceSegmentTextDraft> = {},
): WorkspaceSegmentTextDraft[] {
  if (isListViewDoc(doc)) {
    return extractOrderedSegmentDraftsFromListViewDoc(
      doc,
      orderedSegmentIds,
      previousDraftsBySegmentId,
    );
  }

  if (orderedSegmentIds.length === 0) {
    return [];
  }

  const textBySegmentId = new Map<
    string,
    { stemText: string; terminalText: string }
  >();
  const seenSegmentIds: string[] = [];
  let currentSegmentId: string | null = null;
  let sawPauseBoundarySinceLastSegment = true;
  let encounteredSegmentAnchor = false;
  let pendingStemTextForNextSegment = "";

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
    const isTerminalText = hasTerminalCapsuleMark(node);
    if (!segmentId) {
      if (currentSegmentId !== null && !sawPauseBoundarySinceLastSegment) {
        const currentText = textBySegmentId.get(currentSegmentId) ?? {
          stemText: "",
          terminalText: "",
        };
        textBySegmentId.set(currentSegmentId, {
          stemText: isTerminalText
            ? currentText.stemText
            : `${currentText.stemText}${node.text}`,
          terminalText: isTerminalText
            ? `${currentText.terminalText}${node.text}`
            : currentText.terminalText,
        });
        return;
      }

      pendingStemTextForNextSegment += node.text;
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

    const currentText = textBySegmentId.get(segmentId) ?? {
      stemText: "",
      terminalText: "",
    };
    const nextStemText = `${currentText.stemText}${pendingStemTextForNextSegment}${isTerminalText ? "" : node.text}`;
    textBySegmentId.set(segmentId, {
      stemText: nextStemText,
      terminalText: isTerminalText
        ? `${currentText.terminalText}${node.text}`
        : currentText.terminalText,
    });
    pendingStemTextForNextSegment = "";
  });

  if (!encounteredSegmentAnchor) {
    throw new Error("编辑器 segmentAnchor 已变化，请放弃当前编辑后重试");
  }

  if (pendingStemTextForNextSegment.length > 0) {
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

  return orderedSegmentIds.map((segmentId) => {
    const regions = textBySegmentId.get(segmentId) ?? {
      stemText: "",
      terminalText: "",
    };
    return resolveWorkspaceSegmentDraftFromRegions({
      previousDraft:
        previousDraftsBySegmentId[segmentId] ??
        createEmptyWorkspaceSegmentTextDraft(segmentId),
      stemText: regions.stemText,
      terminalRegionText: regions.terminalText,
    });
  });
}

export function normalizeWorkspaceViewDocToSourceDoc(
  input: NormalizeWorkspaceViewDocInput,
): JSONContent {
  if (isListViewDoc(input.viewDoc)) {
    return normalizeListViewDocToSourceDoc(input);
  }

  const segmentDrafts = extractOrderedSegmentDraftsFromWorkspaceViewDoc(
    input.viewDoc,
    input.orderedSegmentIds,
    input.previousDraftsBySegmentId,
  );

  return buildWorkspaceSourceDoc({
    segments: segmentDrafts.map((segment, index) => ({
      segmentId: segment.segmentId,
      orderKey: index + 1,
      stem: segment.stem,
      terminal_raw: segment.terminal_raw,
      terminal_closer_suffix: segment.terminal_closer_suffix,
      terminal_source: segment.terminal_source,
    })),
    edges: input.edges,
  });
}
