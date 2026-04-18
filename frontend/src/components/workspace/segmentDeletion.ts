import { h, ref } from "vue";
import { ElMessageBox, ElCheckbox } from "element-plus";
import type { JSONContent } from "@tiptap/vue-3";

import {
  buildWorkspaceSegmentTextNodes,
  projectWorkspaceSegmentDraftToRegions,
  type WorkspaceSegmentTextDraft,
} from "./workspace-editor/terminalRegionModel";
import { extractOrderedSegmentDraftsFromWorkspaceViewDoc } from "./workspace-editor/sourceDocNormalizer";
import type { ResolvedLanguage } from "@/types/editSession";

function isMessageBoxCancel(error: unknown): boolean {
  return error === "cancel" || error === "close";
}

function isListViewDoc(doc: JSONContent): boolean {
  return (doc.content ?? []).some((node) => node.type === "segmentBlock");
}

export function detectDeletionCandidates(
  editorDoc: JSONContent,
  orderedSegmentIds: string[],
): string[] {
  const segmentDrafts = extractOrderedSegmentDraftsFromWorkspaceViewDoc(
    editorDoc,
    orderedSegmentIds,
  );
  if (segmentDrafts.length !== orderedSegmentIds.length) {
    return [];
  }

  return segmentDrafts
    .filter(({ stem }) => stem.length === 0)
    .map(({ segmentId }) => segmentId);
}

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

function buildRestoredContent(
  segmentId: string,
  draft: WorkspaceSegmentTextDraft,
  options: {
    detectedLanguage?: ResolvedLanguage | null;
    textLanguage?: string | null;
  } = {},
): JSONContent[] {
  const regions = projectWorkspaceSegmentDraftToRegions({
    draft,
    detectedLanguage: options.detectedLanguage,
    textLanguage: options.textLanguage,
  });
  return buildWorkspaceSegmentTextNodes({
    segmentId,
    stemText: draft.stem,
    terminalText: regions.terminalText,
    terminalSource: draft.terminal_source,
  });
}

function patchListViewDocForRestoredSegments(
  editorDoc: JSONContent,
  restorations: Array<{
    segmentId: string;
    originalDraft: WorkspaceSegmentTextDraft;
    detectedLanguage?: ResolvedLanguage | null;
    textLanguage?: string | null;
  }>,
): JSONContent {
  const doc: JSONContent = JSON.parse(JSON.stringify(editorDoc));
  const restorationMap = new Map(
    restorations.map((restoration) => [restoration.segmentId, restoration]),
  );

  for (const node of doc.content ?? []) {
    if (node.type !== "segmentBlock") {
      continue;
    }

    const segmentId = node.attrs?.segmentId;
    if (typeof segmentId !== "string") {
      continue;
    }

    const restoration = restorationMap.get(segmentId);
    if (!restoration) {
      continue;
    }

    const keepNodes = (node.content ?? []).filter(
      (child: JSONContent) => child.type === "pauseBoundary",
    );
    node.content = [
      ...buildRestoredContent(
        segmentId,
        restoration.originalDraft,
        restoration,
      ),
      ...keepNodes,
    ];
  }

  return doc;
}

function patchLegacyParagraphDocForRestoredSegments(
  editorDoc: JSONContent,
  orderedSegmentIds: string[],
  restorations: Array<{
    segmentId: string;
    originalDraft: WorkspaceSegmentTextDraft;
    detectedLanguage?: ResolvedLanguage | null;
    textLanguage?: string | null;
  }>,
): JSONContent {
  const doc: JSONContent = JSON.parse(JSON.stringify(editorDoc));
  const paragraphs = (doc.content ?? []).filter(
    (n) => n.type === "paragraph",
  );
  const idToIndex = new Map(orderedSegmentIds.map((id, i) => [id, i]));

  for (const restoration of restorations) {
    const { segmentId, originalDraft } = restoration;
    const idx = idToIndex.get(segmentId);
    if (idx === undefined || !paragraphs[idx]) {
      continue;
    }

    const para = paragraphs[idx];
    const keepNodes = (para.content ?? []).filter(
      (n: JSONContent) => n.type === "pauseBoundary",
    );
    para.content = [
      ...buildRestoredContent(segmentId, originalDraft, restoration),
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

export function patchEditorDocForRestoredSegments(
  editorDoc: JSONContent,
  orderedSegmentIds: string[],
  restorations: Array<{
    segmentId: string;
    originalDraft: WorkspaceSegmentTextDraft;
    detectedLanguage?: ResolvedLanguage | null;
    textLanguage?: string | null;
  }>,
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
