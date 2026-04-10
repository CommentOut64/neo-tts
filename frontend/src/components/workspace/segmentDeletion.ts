import { h, ref } from "vue";
import { ElMessageBox, ElCheckbox } from "element-plus";
import type { JSONContent } from "@tiptap/vue-3";

import { extractOrderedSegmentTextsFromWorkspaceViewDoc } from "./workspace-editor/sourceDocNormalizer";

// ── 编辑态空段检测 ──

const SENTENCE_ENDING_PUNCT_ONLY = /^[。！？.!?\s]*$/;

function isMessageBoxCancel(error: unknown): boolean {
  return error === "cancel" || error === "close";
}

function isListViewDoc(doc: JSONContent): boolean {
  return (doc.content ?? []).some((node) => node.type === "segmentBlock");
}

/**
 * 扫描编辑器文档，找出文本仅含句末标点或完全为空的段。
 * list mode 下每个段对应一个 paragraph。
 */
export function detectDeletionCandidates(
  editorDoc: JSONContent,
  orderedSegmentIds: string[],
): string[] {
  const segmentTexts = extractOrderedSegmentTextsFromWorkspaceViewDoc(
    editorDoc,
    orderedSegmentIds,
  );
  if (segmentTexts.length !== orderedSegmentIds.length) {
    return [];
  }

  return segmentTexts
    .filter(({ text }) => SENTENCE_ENDING_PUNCT_ONLY.test(text))
    .map(({ segmentId }) => segmentId);
}

// ── 不再提醒偏好持久化 ──

const STORAGE_KEY = "workspace.autoDeleteEmptySegments";

export function isAutoDeleteSuppressed(): boolean {
  return localStorage.getItem(STORAGE_KEY) === "1";
}

export function setAutoDeleteSuppressed(value: boolean): void {
  if (value) {
    localStorage.setItem(STORAGE_KEY, "1");
  } else {
    localStorage.removeItem(STORAGE_KEY);
  }
}

// ── 编辑态删段确认弹窗（含不再提醒勾选） ──

export async function confirmSegmentDeletion(
  candidateCount: number,
): Promise<boolean> {
  if (isAutoDeleteSuppressed()) {
    return true;
  }

  const checked = ref(false);
  const message = h("div", [
    h(
      "p",
      `检测到 ${candidateCount} 个段的文字已被清空，是否确认删除？`,
    ),
    h(
      "p",
      {
        style:
          "color: var(--el-text-color-secondary); font-size: 12px; margin-top: 4px;",
      },
      "如果不删除，已清空的段会回退为原始文字。",
    ),
    h(
      "label",
      {
        style:
          "display: flex; align-items: center; gap: 6px; margin-top: 12px; cursor: pointer;",
      },
      [
        h(ElCheckbox, {
          modelValue: checked.value,
          "onUpdate:modelValue": (val: boolean) => {
            checked.value = val;
          },
        }),
        h("span", { style: "font-size: 13px;" }, "以后默认删除，不再提醒"),
      ],
    ),
  ]);

  try {
    await ElMessageBox({
      title: "确认删除已清空的段",
      message,
      confirmButtonText: "删除",
      cancelButtonText: "不删除",
      type: "warning",
      closeOnClickModal: false,
      closeOnPressEscape: false,
      lockScroll: false,
    });

    if (checked.value) {
      setAutoDeleteSuppressed(true);
    }
    return true;
  } catch (error) {
    if (isMessageBoxCancel(error)) {
      return false;
    }
    throw error;
  }
}

function patchListViewDocForRestoredSegments(
  editorDoc: JSONContent,
  restorations: Array<{ segmentId: string; originalText: string }>,
): JSONContent {
  const doc: JSONContent = JSON.parse(JSON.stringify(editorDoc));
  const restorationMap = new Map(
    restorations.map(({ segmentId, originalText }) => [segmentId, originalText]),
  );

  for (const node of doc.content ?? []) {
    if (node.type !== "segmentBlock") {
      continue;
    }

    const segmentId = node.attrs?.segmentId;
    if (typeof segmentId !== "string") {
      continue;
    }

    const originalText = restorationMap.get(segmentId);
    if (originalText === undefined) {
      continue;
    }

    const keepNodes = (node.content ?? []).filter(
      (child: JSONContent) => child.type === "pauseBoundary",
    );
    node.content = [
      ...(originalText
        ? [
            {
              type: "text" as const,
              text: originalText,
            },
          ]
        : []),
      ...keepNodes,
    ];
  }

  return doc;
}

function patchLegacyParagraphDocForRestoredSegments(
  editorDoc: JSONContent,
  orderedSegmentIds: string[],
  restorations: Array<{ segmentId: string; originalText: string }>,
): JSONContent {
  const doc: JSONContent = JSON.parse(JSON.stringify(editorDoc));
  const paragraphs = (doc.content ?? []).filter(
    (n) => n.type === "paragraph",
  );
  const idToIndex = new Map(orderedSegmentIds.map((id, i) => [id, i]));

  for (const { segmentId, originalText } of restorations) {
    const idx = idToIndex.get(segmentId);
    if (idx === undefined || !paragraphs[idx]) {
      continue;
    }

    const para = paragraphs[idx];
    const keepNodes = (para.content ?? []).filter(
      (n: JSONContent) => n.type === "pauseBoundary",
    );
    para.content = [
      ...(originalText
        ? [
            {
              type: "text" as const,
              text: originalText,
              marks: [{ type: "segmentAnchor", attrs: { segmentId } }],
            },
          ]
        : []),
      ...keepNodes,
    ];
  }

  return doc;
}

export interface SegmentDeletionRunResult {
  deletedSegmentIds: string[];
  failedSegmentId: string | null;
  completed: boolean;
}

export async function runDeletionJobs(input: {
  segmentIds: string[];
  deleteSegment: (segmentId: string) => Promise<void>;
}): Promise<SegmentDeletionRunResult> {
  const deletedSegmentIds: string[] = [];

  for (const segmentId of input.segmentIds) {
    try {
      await input.deleteSegment(segmentId);
      deletedSegmentIds.push(segmentId);
    } catch {
      return {
        deletedSegmentIds,
        failedSegmentId: segmentId,
        completed: false,
      };
    }
  }

  return {
    deletedSegmentIds,
    failedSegmentId: null,
    completed: true,
  };
}

// ── 编辑器文档修补：将被清空段的文本还原为后端原始值 ──

export function patchEditorDocForRestoredSegments(
  editorDoc: JSONContent,
  orderedSegmentIds: string[],
  restorations: Array<{ segmentId: string; originalText: string }>,
): JSONContent {
  if (isListViewDoc(editorDoc)) {
    return patchListViewDocForRestoredSegments(editorDoc, restorations);
  }

  return patchLegacyParagraphDocForRestoredSegments(
    editorDoc,
    orderedSegmentIds,
    restorations,
  );
}
