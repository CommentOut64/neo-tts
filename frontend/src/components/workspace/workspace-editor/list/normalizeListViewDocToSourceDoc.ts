import type { JSONContent } from "@tiptap/vue-3";

import type { WorkspaceSemanticEdge } from "../layoutTypes";
import { buildWorkspaceSourceDoc } from "../sourceDocModel";
import {
  createEmptyWorkspaceSegmentTextDraft,
  resolveWorkspaceSegmentDraftFromRegions,
  type WorkspaceSegmentTextDraft,
} from "../terminalRegionModel";

export interface NormalizeListViewDocInput {
  viewDoc: JSONContent;
  orderedSegmentIds: string[];
  edges: WorkspaceSemanticEdge[];
  previousDraftsBySegmentId?: Record<string, WorkspaceSegmentTextDraft>;
}

function readSegmentBlockId(node: JSONContent): string | null {
  const segmentId = node.attrs?.segmentId;
  return typeof segmentId === "string" && segmentId.length > 0
    ? segmentId
    : null;
}

function hasTerminalCapsuleMark(node: JSONContent): boolean {
  return (node.marks ?? []).some((mark) => mark.type === "terminalCapsule");
}

function collectSegmentRegions(
  node: JSONContent | undefined,
): { stemText: string; terminalText: string } {
  if (!node) {
    return { stemText: "", terminalText: "" };
  }

  if (typeof node.text === "string") {
    return hasTerminalCapsuleMark(node)
      ? { stemText: "", terminalText: node.text }
      : { stemText: node.text, terminalText: "" };
  }

  if (!node.content || node.content.length === 0) {
    return { stemText: "", terminalText: "" };
  }

  return node.content
    .filter((child) => child.type !== "pauseBoundary")
    .map((child) => collectSegmentRegions(child))
    .reduce(
      (accumulator, current) => ({
        stemText: `${accumulator.stemText}${current.stemText}`,
        terminalText: `${accumulator.terminalText}${current.terminalText}`,
      }),
      { stemText: "", terminalText: "" },
    );
}

export function extractOrderedSegmentDraftsFromListViewDoc(
  doc: JSONContent,
  orderedSegmentIds: string[],
  previousDraftsBySegmentId: Record<string, WorkspaceSegmentTextDraft> = {},
): WorkspaceSegmentTextDraft[] {
  if (orderedSegmentIds.length === 0) {
    return [];
  }

  const segmentBlocks = (doc.content ?? []).filter(
    (node) => node.type === "segmentBlock",
  );
  const orderedSegmentIdSet = new Set(orderedSegmentIds);
  const seenSegmentIds = new Set<string>();
  const segmentBlockById = new Map<string, JSONContent>();

  segmentBlocks.forEach((node) => {
    const segmentId = readSegmentBlockId(node);
    if (!segmentId) {
      throw new Error("编辑器 segmentId 已变化，请放弃当前编辑后重试");
    }
    if (seenSegmentIds.has(segmentId)) {
      throw new Error("编辑器 segmentId 已变化，请放弃当前编辑后重试");
    }
    if (!orderedSegmentIdSet.has(segmentId)) {
      throw new Error("编辑器 segmentId 已变化，请放弃当前编辑后重试");
    }

    seenSegmentIds.add(segmentId);
    segmentBlockById.set(segmentId, node);
  });

  return orderedSegmentIds.map((segmentId) => {
    const node = segmentBlockById.get(segmentId);
    const regions = collectSegmentRegions(node);
    return resolveWorkspaceSegmentDraftFromRegions({
      previousDraft:
        previousDraftsBySegmentId[segmentId] ??
        createEmptyWorkspaceSegmentTextDraft(segmentId),
      stemText: regions.stemText,
      terminalRegionText: regions.terminalText,
    });
  });
}

export function normalizeListViewDocToSourceDoc(
  input: NormalizeListViewDocInput,
): JSONContent {
  const segmentDrafts = extractOrderedSegmentDraftsFromListViewDoc(
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
