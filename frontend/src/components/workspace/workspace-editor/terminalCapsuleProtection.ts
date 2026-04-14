import type { JSONContent } from "@tiptap/vue-3";

import { splitSegmentTerminalCapsule } from "@/utils/segmentTextDisplay";
import { extractOrderedSegmentTextsFromWorkspaceViewDoc } from "./sourceDocNormalizer";

export interface TerminalProtectionInput {
  previousText: string;
  nextText: string;
}

export interface TerminalProtectionResult {
  text: string;
  touchedCapsule: boolean;
  changedText: boolean;
}

export interface SanitizeWorkspaceViewDocTerminalCapsulesInput {
  previousDoc: JSONContent;
  nextDoc: JSONContent;
  orderedSegmentIds: string[];
}

export interface SanitizeWorkspaceViewDocTerminalCapsulesResult {
  doc: JSONContent;
  touchedCapsule: boolean;
  changedText: boolean;
}

export function protectTerminalCapsule(
  input: TerminalProtectionInput,
): TerminalProtectionResult {
  const previousParts = splitSegmentTerminalCapsule(input.previousText);
  const nextParts = splitSegmentTerminalCapsule(input.nextText);

  if (previousParts.capsule.length === 0) {
    return {
      text: input.nextText,
      touchedCapsule: false,
      changedText: input.nextText !== input.previousText,
    };
  }

  const touchedCapsule = nextParts.capsule !== previousParts.capsule;
  if (!touchedCapsule) {
    return {
      text: input.nextText,
      touchedCapsule: false,
      changedText: input.nextText !== input.previousText,
    };
  }

  const looksLikeCapsuleOnlyMutation =
    nextParts.capsule.length === 0 &&
    nextParts.stem.startsWith(previousParts.stem);

  if (looksLikeCapsuleOnlyMutation) {
    return {
      text: input.previousText,
      touchedCapsule: true,
      changedText: false,
    };
  }

  const nextText = `${nextParts.stem}${previousParts.capsule}`;
  return {
    text: nextText,
    touchedCapsule: true,
    changedText: nextText !== input.previousText,
  };
}

function readSegmentAnchorId(node: JSONContent): string | null {
  const anchorMark = (node.marks ?? []).find((mark) => mark.type === "segmentAnchor");
  const segmentId = anchorMark?.attrs?.segmentId;
  return typeof segmentId === "string" && segmentId.length > 0 ? segmentId : null;
}

function isListViewDoc(doc: JSONContent): boolean {
  return (doc.content ?? []).some((node) => node.type === "segmentBlock");
}

function patchListViewDocSegmentTexts(
  doc: JSONContent,
  textBySegmentId: Map<string, string>,
): JSONContent {
  return {
    ...doc,
    content: (doc.content ?? []).map((node) => {
      if (node.type !== "segmentBlock") {
        return node;
      }
      const segmentId = typeof node.attrs?.segmentId === "string" ? node.attrs.segmentId : null;
      if (!segmentId || !textBySegmentId.has(segmentId)) {
        return node;
      }
      const preservedChildren = (node.content ?? []).filter((child) => child.type !== "text");
      const nextText = textBySegmentId.get(segmentId) ?? "";
      return {
        ...node,
        content: nextText.length > 0
          ? [{ type: "text", text: nextText }, ...preservedChildren]
          : preservedChildren,
      };
    }),
  };
}

function patchCompositionViewDocSegmentTexts(
  doc: JSONContent,
  textBySegmentId: Map<string, string>,
): JSONContent {
  const emittedSegmentIds = new Set<string>();

  function patchNode(node: JSONContent): JSONContent {
    if (!node.content || node.content.length === 0) {
      return node;
    }

    if (node.type === "paragraph") {
      const nextContent: JSONContent[] = [];
      for (const child of node.content) {
        const segmentId = readSegmentAnchorId(child);
        if (segmentId) {
          if (emittedSegmentIds.has(segmentId)) {
            continue;
          }
          emittedSegmentIds.add(segmentId);
          nextContent.push({
            type: "text",
            text: textBySegmentId.get(segmentId) ?? child.text ?? "",
            marks: child.marks,
          });
          continue;
        }
        if (typeof child.text === "string") {
          continue;
        }
        nextContent.push(patchNode(child));
      }
      return {
        ...node,
        content: nextContent,
      };
    }

    return {
      ...node,
      content: node.content.map((child) => patchNode(child)),
    };
  }

  return patchNode(doc);
}

export function sanitizeWorkspaceViewDocTerminalCapsules(
  input: SanitizeWorkspaceViewDocTerminalCapsulesInput,
): SanitizeWorkspaceViewDocTerminalCapsulesResult {
  const previousTexts = extractOrderedSegmentTextsFromWorkspaceViewDoc(
    input.previousDoc,
    input.orderedSegmentIds,
  );
  const nextTexts = extractOrderedSegmentTextsFromWorkspaceViewDoc(
    input.nextDoc,
    input.orderedSegmentIds,
  );

  const nextTextBySegmentId = new Map<string, string>();
  let touchedCapsule = false;
  let changedText = false;
  let shouldPatchDoc = false;

  for (let index = 0; index < input.orderedSegmentIds.length; index += 1) {
    const previousEntry = previousTexts[index];
    const nextEntry = nextTexts[index];
    if (!previousEntry || !nextEntry) {
      continue;
    }
    const protectedText = protectTerminalCapsule({
      previousText: previousEntry.text,
      nextText: nextEntry.text,
    });
    nextTextBySegmentId.set(nextEntry.segmentId, protectedText.text);
    touchedCapsule = touchedCapsule || protectedText.touchedCapsule;
    changedText = changedText || protectedText.changedText;
    shouldPatchDoc = shouldPatchDoc || protectedText.text !== nextEntry.text;
  }

  if (!shouldPatchDoc) {
    return {
      doc: input.nextDoc,
      touchedCapsule,
      changedText,
    };
  }

  return {
    doc: isListViewDoc(input.nextDoc)
      ? patchListViewDocSegmentTexts(input.nextDoc, nextTextBySegmentId)
      : patchCompositionViewDocSegmentTexts(input.nextDoc, nextTextBySegmentId),
    touchedCapsule,
    changedText,
  };
}
