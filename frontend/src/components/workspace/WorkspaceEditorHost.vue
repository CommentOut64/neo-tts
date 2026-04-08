<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import type { JSONContent } from "@tiptap/vue-3";

import { useEditSession } from "@/composables/useEditSession";
import { useInputDraft } from "@/composables/useInputDraft";
import { usePlayback } from "@/composables/usePlayback";
import { useRuntimeState } from "@/composables/useRuntimeState";
import { useWorkspaceProcessing } from "@/composables/useWorkspaceProcessing";
import { useSegmentSelection } from "@/composables/useSegmentSelection";
import { useWorkspaceDraftPersistence } from "@/composables/useWorkspaceDraftPersistence";
import { useWorkspaceLightEdit } from "@/composables/useWorkspaceLightEdit";
import { useParameterPanel } from "@/composables/useParameterPanel";
import type { EditableEdge } from "@/types/editSession";
import { extractWorkspaceEffectiveText } from "@/utils/workspaceEffectiveText";
import type { WorkspaceDraftMode } from "@/utils/workspaceDraftSnapshot";

import ResetSessionDialog from "./ResetSessionDialog.vue";
import { buildSessionHeadText } from "./sessionHandoff";
import { buildEditorExtensions } from "./workspace-editor/buildEditorExtensions";
import { buildWorkspaceSemanticDocument } from "./workspace-editor/buildWorkspaceSemanticDocument";
import {
  buildWorkspaceRenderPlan,
  collectSegmentDraftChanges,
} from "./workspace-editor/documentModel";
import { extractRenderMapFromDoc } from "./workspace-editor/extractRenderMapFromDoc";
import type { WorkspaceEditorLayoutMode } from "./workspace-editor/layoutTypes";
import { segmentDecorationKey } from "./workspace-editor/segmentDecoration";
import {
  collectPauseBoundaryAttrPatches,
  findCanvasTarget,
  haveSameEdgeTopology,
  requestLayoutMode,
} from "./workspace-editor/workspaceEditorHostModel";

const emit = defineEmits<{
  (e: "backfill-to-text-input"): void;
}>();

const WORKSPACE_DRAFT_SAVE_DEBOUNCE_MS = 200;
const COMPOSITION_DISABLED_MESSAGE =
  "当前会话结构已脱离输入稿换行，暂不支持组合式";

const editSession = useEditSession();
const inputDraft = useInputDraft();
const lightEdit = useWorkspaceLightEdit();
const workspaceDraftPersistence = useWorkspaceDraftPersistence();
const { currentSegmentId, play, seekToSegment } = usePlayback();
const runtimeState = useRuntimeState();
const workspaceProcessing = useWorkspaceProcessing();
const segmentSelection = useSegmentSelection();
const parameterPanel = useParameterPanel();

const resetSessionDialogVisible = ref(false);
const isEditing = ref(false);
const docJson = ref<JSONContent>({
  type: "doc",
  content: [{ type: "paragraph", content: [] }],
});
const layoutMode = ref<WorkspaceEditorLayoutMode>("composition");
const restoredSessionKey = ref<string | null>(null);
const renderMap = ref<ReturnType<typeof extractRenderMapFromDoc> | null>(null);
const editorRef = ref<{ editor: any } | null>(null);

let draftPersistTimeoutId: number | null = null;

const sortedReadySegments = computed(() =>
  [...editSession.segments.value].sort((left, right) => left.order_key - right.order_key),
);

const currentDocumentId = computed(
  () =>
    sortedReadySegments.value[0]?.document_id ??
    editSession.snapshot.value?.document_id ??
    null,
);

const currentDocumentVersion = computed(() => editSession.documentVersion.value);
const currentSessionHeadText = computed(() =>
  buildSessionHeadText(sortedReadySegments.value),
);
const currentSessionSegmentIds = computed(() =>
  sortedReadySegments.value.map((segment) => segment.segment_id),
);

const currentSessionKey = computed(() => {
  if (
    editSession.sessionStatus.value !== "ready" ||
    runtimeState.isInitialRendering.value ||
    !editSession.segmentsLoaded.value ||
    !currentDocumentId.value ||
    currentDocumentVersion.value === null
  ) {
    return null;
  }

  return [
    currentDocumentId.value,
    String(currentDocumentVersion.value),
    currentSessionSegmentIds.value.join("|"),
  ].join("::");
});

const semanticDocument = computed(() => {
  if (editSession.sessionStatus.value === "ready") {
    return buildWorkspaceSemanticDocument({
      sourceText: editSession.sourceText.value,
      segments: sortedReadySegments.value.map((segment) => ({
        segmentId: segment.segment_id,
        orderKey: segment.order_key,
        text: lightEdit.getDraft(segment.segment_id) ?? segment.raw_text,
        renderStatus: "completed",
      })),
      edges: editSession.edges.value.map((edge) => ({
        edgeId: edge.edge_id,
        leftSegmentId: edge.left_segment_id,
        rightSegmentId: edge.right_segment_id,
        pauseDurationSeconds: edge.pause_duration_seconds,
        boundaryStrategy: edge.boundary_strategy,
      })),
      dirtySegmentIds: lightEdit.dirtySegmentIds.value,
    });
  }

  if (runtimeState.isInitialRendering.value) {
    return buildWorkspaceSemanticDocument({
      sourceText: editSession.sourceText.value,
      segments: runtimeState.progressiveSegments.value.map((segment) => ({
        segmentId: segment.segmentId,
        orderKey: segment.orderKey,
        text: segment.rawText,
        renderStatus: segment.renderStatus,
      })),
      edges: [],
      dirtySegmentIds: new Set<string>(),
    });
  }

  return buildWorkspaceSemanticDocument({
    sourceText: null,
    segments: [],
    edges: [],
    dirtySegmentIds: new Set<string>(),
  });
});

const effectiveLayoutMode = computed<WorkspaceEditorLayoutMode>(() => {
  return layoutMode.value === "composition" &&
    semanticDocument.value.compositionAvailability.ready
    ? "composition"
    : "list";
});

const renderPlan = computed(() =>
  buildWorkspaceRenderPlan(semanticDocument.value, effectiveLayoutMode.value),
);

const orderedSegmentIds = computed(
  () => renderPlan.value.renderMap.orderedSegmentIds,
);
const segmentCount = computed(() => orderedSegmentIds.value.length);
const charCount = computed(() => {
  const editor = editorRef.value?.editor;
  return editor ? editor.state.doc.textContent.length : 0;
});
const modeLabel = computed(() => (isEditing.value ? "编辑" : "展示"));
const compositionAvailable = computed(
  () => semanticDocument.value.compositionAvailability.ready,
);
const isInteractionLocked = computed(
  () => workspaceProcessing.isInteractionLocked.value,
);

const structuralDocSignature = computed(() =>
  JSON.stringify({
    layoutMode: effectiveLayoutMode.value,
    blocks: semanticDocument.value.sourceBlocks,
    segments: semanticDocument.value.segmentOrder.map((segmentId) => {
      const segment = semanticDocument.value.segmentsById[segmentId];
      return {
        segmentId,
        text: segment?.text ?? "",
        renderStatus: segment?.renderStatus ?? "pending",
      };
    }),
    edgeTopology: semanticDocument.value.segmentOrder
      .map((segmentId) => semanticDocument.value.edgesByLeftSegmentId[segmentId])
      .filter(Boolean)
      .map((edge) => ({
        edgeId: edge.edgeId,
        leftSegmentId: edge.leftSegmentId,
        rightSegmentId: edge.rightSegmentId,
      })),
  }),
);

const customExtensions = buildEditorExtensions({
  onActivateEdge(edgeId) {
    if (isEditing.value || !edgeId) {
      return;
    }
    segmentSelection.selectEdge(edgeId);
  },
});

function clearPendingDraftPersist() {
  if (draftPersistTimeoutId === null) {
    return;
  }

  window.clearTimeout(draftPersistTimeoutId);
  draftPersistTimeoutId = null;
}

onBeforeUnmount(() => {
  clearPendingDraftPersist();
});

function buildSegmentDraftRecord(
  drafts: Map<string, string> = lightEdit.draftTextBySegmentId.value,
): Record<string, string> {
  return Object.fromEntries(drafts);
}

function syncInputBackToSessionIfNeeded() {
  if (inputDraft.source.value !== "workspace" || !currentSessionHeadText.value) {
    return;
  }

  editSession.syncInputDraftToSessionText(currentSessionHeadText.value);
}

function syncInputFromWorkspaceEffectiveText(effectiveText: string) {
  if (
    effectiveText !== currentSessionHeadText.value ||
    inputDraft.source.value === "workspace"
  ) {
    inputDraft.syncFromWorkspaceDraft(effectiveText);
  }
}

function persistWorkspaceDraftSnapshot(
  mode: WorkspaceDraftMode,
  editorDoc: JSONContent,
  segmentDrafts: Record<string, string> = buildSegmentDraftRecord(),
) {
  if (!currentDocumentId.value || currentDocumentVersion.value === null) {
    return;
  }

  workspaceDraftPersistence.saveSnapshot({
    schemaVersion: 1,
    documentId: currentDocumentId.value,
    documentVersion: currentDocumentVersion.value,
    segmentIds: [...currentSessionSegmentIds.value],
    mode,
    editorDoc,
    segmentDrafts,
    effectiveText: extractWorkspaceEffectiveText(editorDoc),
    updatedAt: new Date().toISOString(),
  });
}

function clearPersistedWorkspaceDraft() {
  if (!currentDocumentId.value) {
    return;
  }

  workspaceDraftPersistence.clearSnapshot(currentDocumentId.value);
}

function syncPreviewWorkspaceState(editorDoc: JSONContent) {
  if (lightEdit.dirtyCount.value === 0) {
    clearPersistedWorkspaceDraft();
    syncInputBackToSessionIfNeeded();
    return;
  }

  const effectiveText = extractWorkspaceEffectiveText(editorDoc);
  persistWorkspaceDraftSnapshot("preview", editorDoc);
  syncInputFromWorkspaceEffectiveText(effectiveText);
}

function pushContentToEditor(
  editorOverride?: any,
  docOverride: JSONContent = docJson.value,
) {
  nextTick(() => {
    const editor = editorOverride ?? editorRef.value?.editor;
    if (!editor) {
      return;
    }

    editor.commands.setContent(docOverride);
    renderMap.value = extractRenderMapFromDoc(
      editor.getJSON(),
      renderPlan.value.renderMap.orderedSegmentIds,
      effectiveLayoutMode.value,
    );
    syncDecorationState(editor);
  });
}

function syncDisplayDocument() {
  if (isEditing.value) {
    return;
  }

  docJson.value = renderPlan.value.doc;
  pushContentToEditor(undefined, renderPlan.value.doc);

  if (
    editSession.sessionStatus.value === "ready" &&
    !runtimeState.isInitialRendering.value
  ) {
    syncPreviewWorkspaceState(renderPlan.value.doc);
  }
}

function syncDecorationState(editorOverride?: any) {
  const editor = editorOverride ?? editorRef.value?.editor;
  if (!editor) {
    return;
  }

  editor.storage.segmentDecoration.state = {
    layoutMode: effectiveLayoutMode.value,
    renderMap: renderMap.value,
    playingId: currentSegmentId.value,
    selectedIds: segmentSelection.selectedSegmentIds.value,
    dirtyIds: lightEdit.dirtySegmentIds.value,
    dirtyEdgeIds: parameterPanel.dirtyEdgeIds.value,
    isEditing: isEditing.value,
  };

  editor.view.dispatch(editor.state.tr.setMeta(segmentDecorationKey, true));
}

function isEditorSnapshotCompatible(editorDoc: JSONContent): boolean {
  const extracted = extractRenderMapFromDoc(
    editorDoc,
    currentSessionSegmentIds.value,
    effectiveLayoutMode.value,
  );
  return (
    currentSessionSegmentIds.value.length === 0 ||
    extracted.segmentRanges.length > 0
  );
}

function requestNextLayoutMode(nextMode: WorkspaceEditorLayoutMode) {
  const result = requestLayoutMode({
    isEditing: isEditing.value,
    currentMode: layoutMode.value,
    nextMode,
  });
  if (result.warning) {
    ElMessage.warning(result.warning);
  }
  layoutMode.value = result.layoutMode;
}

function getBackendSegmentText(segmentId: string): string {
  const segment = editSession.segments.value.find(
    (item) => item.segment_id === segmentId,
  );
  return segment?.raw_text ?? "";
}

function syncPauseBoundaryAttrsInEditor(nextEdges: EditableEdge[]) {
  const editor = editorRef.value?.editor;
  if (!editor || !renderMap.value) {
    return;
  }

  const patches = collectPauseBoundaryAttrPatches({
    doc: editor.getJSON(),
    renderMap: renderMap.value,
    edges: nextEdges,
  });
  if (patches.length === 0) {
    return;
  }

  let transaction = editor.state.tr;
  let changed = false;

  for (const patch of patches) {
    const node = editor.state.doc.nodeAt(patch.from);
    if (!node || node.type.name !== "pauseBoundary") {
      continue;
    }

    transaction = transaction.setNodeMarkup(patch.from, undefined, patch.attrs);
    changed = true;
  }

  if (!changed) {
    return;
  }

  editor.view.dispatch(transaction);
  renderMap.value = extractRenderMapFromDoc(
    editor.getJSON(),
    renderPlan.value.renderMap.orderedSegmentIds,
    effectiveLayoutMode.value,
  );
  syncDecorationState(editor);
}

function onEditorCreate({ editor }: { editor: any }) {
  editor.setEditable(isEditing.value);
  pushContentToEditor(editor);
}

function enterEditMode(clickEvent?: MouseEvent) {
  if (isEditing.value) {
    return;
  }
  if (isInteractionLocked.value) {
    ElMessage.warning("当前正在处理正式结果，暂时不能编辑正文");
    return;
  }

  segmentSelection.clearSelection();
  isEditing.value = true;

  nextTick(() => {
    const editor = editorRef.value?.editor;
    if (!editor) {
      return;
    }

    if (clickEvent) {
      const position = editor.view.posAtCoords({
        left: clickEvent.clientX,
        top: clickEvent.clientY,
      });
      editor.commands.focus();
      if (position) {
        editor.commands.setTextSelection(position.pos);
      }
    } else {
      editor.commands.focus();
    }

    syncDecorationState(editor);
  });
}

function commitAndExitEdit() {
  const editor = editorRef.value?.editor;
  if (!editor) {
    clearPendingDraftPersist();
    isEditing.value = false;
    nextTick(syncDisplayDocument);
    return;
  }

  try {
    const editorDoc = editor.getJSON();
    const changes = collectSegmentDraftChanges(
      editorDoc,
      renderPlan.value.renderMap.orderedSegmentIds,
      getBackendSegmentText,
    );

    const nextDrafts = new Map(lightEdit.draftTextBySegmentId.value);
    changes.changedDrafts.forEach(([segmentId, text]) => {
      nextDrafts.set(segmentId, text);
    });
    changes.clearedSegmentIds.forEach((segmentId) => {
      nextDrafts.delete(segmentId);
    });

    clearPendingDraftPersist();
    docJson.value = editorDoc;
    lightEdit.replaceAllDrafts(nextDrafts);

    if (nextDrafts.size > 0) {
      persistWorkspaceDraftSnapshot(
        "preview",
        editorDoc,
        buildSegmentDraftRecord(nextDrafts),
      );
      syncInputFromWorkspaceEffectiveText(extractWorkspaceEffectiveText(editorDoc));
    } else {
      clearPersistedWorkspaceDraft();
      syncInputBackToSessionIfNeeded();
    }
  } catch (error) {
    ElMessage.error(
      error instanceof Error ? error.message : "正文结构异常，无法提交编辑",
    );
    return;
  }

  isEditing.value = false;
  nextTick(syncDisplayDocument);
}

function discardAndExitEdit() {
  clearPendingDraftPersist();
  isEditing.value = false;
  nextTick(syncDisplayDocument);
}

function handleResetSessionSuccess() {
  segmentSelection.clearSelection();
  lightEdit.clearAll();
  clearPendingDraftPersist();
  isEditing.value = false;
  nextTick(syncDisplayDocument);
}

function onKeyDown(event: KeyboardEvent) {
  if (event.key === "Escape" && isEditing.value) {
    event.preventDefault();
    event.stopPropagation();
    commitAndExitEdit();
  }
}

function onDocUpdate(value: JSONContent) {
  if (!isEditing.value) {
    return;
  }

  docJson.value = value;
  clearPendingDraftPersist();
  draftPersistTimeoutId = window.setTimeout(() => {
    draftPersistTimeoutId = null;
    persistWorkspaceDraftSnapshot("editing", value);
    syncInputFromWorkspaceEffectiveText(extractWorkspaceEffectiveText(value));
  }, WORKSPACE_DRAFT_SAVE_DEBOUNCE_MS);
}

function onCanvasClick(event: MouseEvent) {
  if (isEditing.value) {
    return;
  }
  if (isInteractionLocked.value) {
    return;
  }

  const target = findCanvasTarget(event.target as any);
  if (!target) {
    segmentSelection.clearSelection();
    return;
  }

  if (target.type === "edge" && target.edgeId) {
    segmentSelection.selectEdge(target.edgeId);
    return;
  }

  if (target.type !== "segment" || !target.segmentId) {
    segmentSelection.clearSelection();
    return;
  }

  const allIds = orderedSegmentIds.value;
  if (event.shiftKey) {
    segmentSelection.rangeSelect(target.segmentId, allIds);
  } else if (event.ctrlKey || event.metaKey) {
    segmentSelection.toggleSelect(target.segmentId);
  } else {
    segmentSelection.select(target.segmentId);
  }

  seekToSegment(target.segmentId);
  play();
}

function onCanvasDblClick(event: MouseEvent) {
  if (isEditing.value) {
    return;
  }
  if (isInteractionLocked.value) {
    return;
  }

  const target = findCanvasTarget(event.target as any);
  if (target?.type === "segment" && target.segmentId) {
    window.getSelection()?.removeAllRanges();
    enterEditMode(event);
  }
}

watch(
  currentSessionKey,
  () => {
    if (!currentSessionKey.value) {
      restoredSessionKey.value = null;
      return;
    }

    const snapshot = workspaceDraftPersistence.readCompatibleSnapshot({
      documentId: currentDocumentId.value!,
      documentVersion: currentDocumentVersion.value!,
      segmentIds: currentSessionSegmentIds.value,
    });

    clearPendingDraftPersist();
    if (snapshot) {
      lightEdit.replaceAllDrafts(snapshot.segmentDrafts);
      syncInputFromWorkspaceEffectiveText(snapshot.effectiveText);

      if (
        snapshot.mode === "editing" &&
        isEditorSnapshotCompatible(snapshot.editorDoc)
      ) {
        isEditing.value = true;
        docJson.value = snapshot.editorDoc;
        pushContentToEditor(undefined, snapshot.editorDoc);
      } else {
        isEditing.value = false;
        syncDisplayDocument();
      }
    } else {
      isEditing.value = false;
      syncDisplayDocument();
    }

    restoredSessionKey.value = currentSessionKey.value;
  },
  { immediate: true },
);

watch(
  () => semanticDocument.value.compositionAvailability.ready,
  (ready) => {
    if (!ready && layoutMode.value === "composition") {
      layoutMode.value = "list";
    }
  },
  { immediate: true },
);

watch(
  structuralDocSignature,
  () => {
    if (!isEditing.value) {
      syncDisplayDocument();
    }
  },
  { immediate: true },
);

watch(
  () => editSession.edges.value,
  (nextEdges, previousEdges) => {
    if (!haveSameEdgeTopology(nextEdges, previousEdges)) {
      if (!isEditing.value) {
        syncDisplayDocument();
      }
      return;
    }

    if (!isEditing.value) {
      syncPauseBoundaryAttrsInEditor(nextEdges);
    }
  },
  { deep: true },
);

watch(
  [
    currentSegmentId,
    () => segmentSelection.selectedSegmentIds.value,
    () => lightEdit.dirtySegmentIds.value,
    () => parameterPanel.dirtyEdgeIds.value,
    isEditing,
    renderMap,
  ],
  () => nextTick(syncDecorationState),
  { deep: true },
);

watch(
  () => editorRef.value?.editor,
  (editor) => {
    if (!editor) {
      return;
    }
    editor.setEditable(isEditing.value);
    pushContentToEditor(editor);
  },
  { immediate: true },
);

watch(isEditing, (editing) => {
  const editor = editorRef.value?.editor;
  if (!editor) {
    return;
  }

  editor.setEditable(editing);
  nextTick(() => syncDecorationState(editor));
});
</script>

<template>
  <section
    class="animate-fall flex min-h-0 w-full flex-1 flex-col overflow-hidden rounded-card border border-border bg-card shadow-card dark:border-transparent"
    @keydown="onKeyDown"
  >
    <header
      class="flex h-12 shrink-0 items-center justify-between border-b border-border/70 px-4 dark:border-border/30"
    >
      <div class="flex min-w-0 items-center gap-2">
        <h3 class="text-sm font-semibold leading-none text-foreground">
          会话正文
        </h3>
        <span
          class="rounded px-1.5 py-0.5 text-[10px] font-medium leading-none"
          :class="isEditing
            ? 'border border-blue-500/20 bg-blue-500/10 text-blue-600'
            : 'border border-border/50 bg-muted text-muted-fg'"
        >
          {{ modeLabel }}
        </span>
        <div class="inline-flex overflow-hidden rounded border border-border">
          <button
            type="button"
            class="px-2.5 py-1 text-xs transition-colors"
            :class="effectiveLayoutMode === 'composition'
              ? 'bg-foreground text-background'
              : 'bg-transparent text-foreground'"
            :disabled="isEditing || !compositionAvailable || isInteractionLocked"
            @click="requestNextLayoutMode('composition')"
          >
            组合式
          </button>
          <button
            type="button"
            class="px-2.5 py-1 text-xs transition-colors"
            :class="effectiveLayoutMode === 'list'
              ? 'bg-foreground text-background'
              : 'bg-transparent text-foreground'"
            :disabled="isEditing || isInteractionLocked"
            @click="requestNextLayoutMode('list')"
          >
            列表式
          </button>
        </div>
        <el-tooltip
          v-if="!compositionAvailable"
          :content="COMPOSITION_DISABLED_MESSAGE"
          placement="bottom"
        >
          <span
            class="inline-flex h-5 shrink-0 items-center rounded border border-border px-1.5 text-[11px] text-muted-fg"
          >
            仅列表式
          </span>
        </el-tooltip>
      </div>

      <div class="flex min-w-[240px] items-center justify-end gap-2">
        <span class="mr-1 text-xs text-muted-fg">{{ charCount }} 字</span>

        <button
          v-if="!isEditing"
          :disabled="segmentCount === 0 || isInteractionLocked"
          class="rounded border border-border px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:bg-secondary/50 disabled:cursor-not-allowed disabled:opacity-50"
          @click="emit('backfill-to-text-input')"
        >
          转到文本输入页继续编辑
        </button>
        <button
          v-if="!isEditing && segmentCount > 0"
          class="rounded border border-border px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:bg-secondary/50"
          :disabled="isInteractionLocked"
          @click="enterEditMode"
        >
          编辑正文
        </button>
        <button
          v-if="!isEditing"
          class="rounded border border-destructive/30 px-2.5 py-1 text-xs font-medium text-destructive transition-colors hover:bg-destructive/10"
          :disabled="isInteractionLocked"
          @click="resetSessionDialogVisible = true"
        >
          清空会话
        </button>

        <template v-if="isEditing">
          <button
            class="rounded px-2.5 py-1 text-xs font-medium text-muted-fg transition-colors hover:bg-secondary/50"
            :disabled="isInteractionLocked"
            @click="discardAndExitEdit"
          >
            放弃
          </button>
          <button
            class="hover-state-layer rounded bg-blue-500 px-2.5 py-1 text-xs font-medium text-white shadow-sm transition-colors"
            :disabled="isInteractionLocked"
            @click="commitAndExitEdit"
          >
            完成编辑
          </button>
        </template>
      </div>
    </header>

    <div
      class="flex-1 overflow-y-auto scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent"
      @click="onCanvasClick"
      @dblclick="onCanvasDblClick"
    >
      <UEditor
        ref="editorRef"
        :model-value="docJson"
        content-type="json"
        :on-create="onEditorCreate"
        :extensions="customExtensions"
        :starter-kit="{ heading: false, horizontalRule: false, blockquote: false, codeBlock: false }"
        :placeholder="{ placeholder: '会话正文将在这里显示', mode: 'firstLine' }"
        :ui="{ base: 'px-3 py-2 min-h-full' }"
        class="min-h-full w-full"
        @update:model-value="onDocUpdate"
      />
    </div>

    <ResetSessionDialog
      v-model:visible="resetSessionDialogVisible"
      @success="handleResetSessionSuccess"
    />
  </section>
</template>

<style scoped>
:deep(.ProseMirror) {
  min-height: 100%;
  color: var(--color-foreground);
  font-family: inherit;
  font-size: 0.9375rem;
  line-height: 1.75;
  outline: none;
}

:deep(.ProseMirror ::selection) {
  background: rgba(59, 130, 246, 0.25);
}

html.dark :deep(.ProseMirror ::selection) {
  background: rgba(96, 165, 250, 0.35);
}

:deep(.ProseMirror > *) {
  margin-top: 0;
  margin-bottom: 0;
}

:deep(.ProseMirror p) {
  margin: 0;
  padding: 6px 10px;
}

:deep(.segment-fragment) {
  border-radius: 4px;
  box-decoration-break: clone;
  -webkit-box-decoration-break: clone;
  padding: 1px 0;
  transition:
    background-color 0.15s ease,
    color 0.3s ease,
    box-shadow 0.15s ease;
}

:deep(.segment-dirty) {
  background: rgba(245, 158, 11, 0.06);
  box-shadow: inset 3px 0 0 var(--color-warning);
}

html.dark :deep(.segment-dirty) {
  background: rgba(245, 158, 11, 0.10);
}

:deep(.segment-playing) {
  color: var(--color-accent);
  font-weight: 700;
}

:deep(.segment-selected) {
  background: rgba(59, 130, 246, 0.12);
}

html.dark :deep(.segment-selected) {
  background: rgba(96, 165, 250, 0.18);
}

:deep(.ProseMirror p.segment-line) {
  border-left: 3px solid transparent;
  border-radius: 8px;
  transition:
    background-color 0.15s ease,
    color 0.3s ease,
    box-shadow 0.15s ease,
    border-color 0.15s ease;
}

:deep(.ProseMirror p.segment-line-dirty) {
  border-left-color: var(--color-warning) !important;
  background: rgba(245, 158, 11, 0.06);
}

html.dark :deep(.ProseMirror p.segment-line-dirty) {
  background: rgba(245, 158, 11, 0.10);
}

:deep(.ProseMirror p.segment-line-selected) {
  background: rgba(59, 130, 246, 0.12);
}

html.dark :deep(.ProseMirror p.segment-line-selected) {
  background: rgba(96, 165, 250, 0.18);
}

:deep(.ProseMirror p.segment-line-playing) {
  color: var(--color-accent);
  font-weight: 700;
}

:deep(.ProseMirror p.segment-line [data-edge-id] button) {
  transition:
    background-color 0.15s ease,
    color 0.3s ease,
    border-color 0.15s ease,
    box-shadow 0.15s ease;
}

:deep(.ProseMirror p.segment-line-selected [data-edge-id] button) {
  background: rgba(59, 130, 246, 0.12);
  border-color: rgba(59, 130, 246, 0.28);
  color: rgb(37 99 235);
}

html.dark :deep(.ProseMirror p.segment-line-selected [data-edge-id] button) {
  background: rgba(96, 165, 250, 0.18);
  border-color: rgba(96, 165, 250, 0.3);
  color: rgb(147 197 253);
}

:deep(.ProseMirror p.segment-line-playing [data-edge-id] button) {
  background: color-mix(in srgb, var(--color-accent) 12%, transparent);
  border-color: color-mix(in srgb, var(--color-accent) 35%, transparent);
  color: var(--color-accent);
}

:deep(.ProseMirror .pause-boundary-dirty) {
  background: rgba(245, 158, 11, 0.12);
  border-color: rgba(245, 158, 11, 0.35);
  box-shadow: inset 0 0 0 1px rgba(245, 158, 11, 0.15);
  color: rgb(217 119 6);
}

html.dark :deep(.ProseMirror .pause-boundary-dirty) {
  background: rgba(245, 158, 11, 0.16);
  border-color: rgba(245, 158, 11, 0.4);
  color: rgb(251 191 36);
}

:deep(.ProseMirror .is-editor-empty:first-child::before) {
  color: var(--color-muted-fg);
  opacity: 0.5;
}
</style>
