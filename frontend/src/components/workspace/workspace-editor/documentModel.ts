import type { JSONContent } from "@tiptap/vue-3";

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
  return {
    type: "doc",
    content:
      segments.length > 0
        ? segments.map((segment) => ({
            type: "paragraph",
            content: segment.text
              ? [{ type: "text", text: segment.text }]
              : [],
          }))
        : [{ type: "paragraph", content: [] }],
  };
}

export function collectSegmentDraftChanges(
  doc: JSONContent,
  orderedSegmentIds: string[],
  getBackendText: (segmentId: string) => string,
): SegmentDraftChangeSet {
  const paragraphs = (doc.content ?? []).filter(
    (node) => node.type === "paragraph",
  );

  if (paragraphs.length !== orderedSegmentIds.length) {
    throw new Error("编辑器段落结构已变化，请放弃当前编辑后重试");
  }

  const changedDrafts: Array<[segmentId: string, text: string]> = [];
  const clearedSegmentIds: string[] = [];

  orderedSegmentIds.forEach((segmentId, index) => {
    const currentText = readNodeText(paragraphs[index]);
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

function readNodeText(node: JSONContent | undefined): string {
  if (!node?.content || node.content.length === 0) {
    return "";
  }

  return node.content
    .map((child) => {
      if (typeof child.text === "string") {
        return child.text;
      }

      return readNodeText(child);
    })
    .join("");
}
