<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import type { JSONContent } from "@tiptap/vue-3";

import { reorderSegments, deleteSegment } from "@/api/editSession";
import { useEditSession } from "@/composables/useEditSession";
import { usePlayback } from "@/composables/usePlayback";
import { useRuntimeState } from "@/composables/useRuntimeState";
import { useWorkspaceProcessing } from "@/composables/useWorkspaceProcessing";
import { useSegmentSelection } from "@/composables/useSegmentSelection";
import { useWorkspaceDraftPersistence } from "@/composables/useWorkspaceDraftPersistence";
import { registerWorkspaceExitHandlers } from "@/composables/useWorkspaceExitBridge";
import { useWorkspaceLightEdit } from "@/composables/useWorkspaceLightEdit";
import { useWorkspaceAutoplay } from "@/composables/useWorkspaceAutoplay";
import { useParameterPanel } from "@/composables/useParameterPanel";
import { useWorkspaceListReorder } from "@/composables/useWorkspaceListReorder";
import { useWorkspaceReorderDraft } from "@/composables/useWorkspaceReorderDraft";
import type { EditableEdge, EditableSegment } from "@/types/editSession";
import { buildSegmentDisplayText } from "@/utils/segmentTextDisplay";
import { extractWorkspaceEffectiveText } from "@/utils/workspaceEffectiveText";
import {
  WORKSPACE_DRAFT_SCHEMA_VERSION,
  type WorkspaceDraftMode,
} from "@/utils/workspaceDraftSnapshot";

import EndSessionDialog from "./EndSessionDialog.vue";
import SegmentContextMenu from "./SegmentContextMenu.vue";
import {
  detectDeletionCandidates,
  confirmSegmentDeletion,
  patchEditorDocForRestoredSegments,
  runDeletionJobs,
} from "./segmentDeletion";
import {
  buildSessionHeadText,
  resolveEndSessionChoiceResult,
  resolveEndSessionGuard,
  type EndSessionGuard,
  type EndSessionChoice,
} from "./sessionHandoff";
import { resolveRerenderTargets } from "./rerenderTargets";
import { buildEditorExtensions } from "./workspace-editor/buildEditorExtensions";
import { buildDisplayWorkspaceEdges } from "./workspace-editor/buildDisplayWorkspaceEdges";
import { buildWorkspaceSemanticDocument } from "./workspace-editor/buildWorkspaceSemanticDocument";
import {
  areCompositionLayoutHintsCompatible,
  buildCompositionLayoutHintsFromSourceBlocks,
  buildCompositionLayoutHintsFromViewDoc,
  type WorkspaceCompositionLayoutHints,
} from "./workspace-editor/compositionLayoutHints";
import { buildWorkspaceRenderPlan } from "./workspace-editor/documentModel";
import { extractRenderMapFromDoc } from "./workspace-editor/extractRenderMapFromDoc";
import type { WorkspaceEditorLayoutMode } from "./workspace-editor/layoutTypes";
import type { WorkspaceSemanticEdge } from "./workspace-editor/layoutTypes";
import { createEmptyWorkspaceSourceDoc, buildWorkspaceSourceDoc } from "./workspace-editor/sourceDocModel";
import {
  extractOrderedSegmentDraftsFromWorkspaceViewDoc,
  normalizeWorkspaceViewDocToSourceDoc,
} from "./workspace-editor/sourceDocNormalizer";
import { segmentDecorationKey } from "./workspace-editor/segmentDecoration";
import {
  buildWorkspaceSegmentDisplayTextFromDraft,
  createEmptyWorkspaceSegmentTextDraft,
  type WorkspaceSegmentTextDraft,
} from "./workspace-editor/terminalRegionModel";
import EditorSelectionHintBubble from "./workspace-editor/EditorSelectionHintBubble.vue";
import {
  canStartListReorder,
  buildWorkspaceDraftPersistKey,
  buildWorkspaceViewRevisionKey,
  cloneWorkspaceSerializable,
  collectPauseBoundaryAttrPatches,
  findCanvasTarget,
  findReorderHandleTarget,
  haveSameEdgeTopology,
  resolveSegmentDeletionGuard,
  resolveWorkspaceSessionItems,
  requestLayoutMode,
  shouldBlockEdgeEditing,
  shouldPreserveLocalTextDraftsOnVersionChange,
} from "./workspace-editor/workspaceEditorHostModel";

const WORKSPACE_DRAFT_SAVE_DEBOUNCE_MS = 200;
const COMPOSITION_DISABLED_MESSAGE =
  "当前会话结构已脱离输入稿换行，暂不支持组合式";
const REORDER_DRAFT_LOCK_MESSAGE = "请先应用或放弃当前顺序调整";
const EDITOR_TERMINAL_HINT_MESSAGE = "句末标点不可修改";
const EDITOR_TERMINAL_HINT_THROTTLE_MS = 900;
const EDITOR_TERMINAL_HINT_HIDE_MS = 1400;

const editSession = useEditSession();
const lightEdit = useWorkspaceLightEdit();
const workspaceDraftPersistence = useWorkspaceDraftPersistence();
const { currentCursor, isPlaying, play, pause, seekToSegment } = usePlayback();
const runtimeState = useRuntimeState();
const workspaceProcessing = useWorkspaceProcessing();
const segmentSelection = useSegmentSelection();
const { isAutoPlayEnabled, toggleAutoPlay } = useWorkspaceAutoplay();
const parameterPanel = useParameterPanel();
const reorderDraft = useWorkspaceReorderDraft();

const endSessionDialogVisible = ref(false);
const endSessionDialogMode = ref<EndSessionGuard>("confirm_plain");
const isEndingSession = ref(false);
const isEditing = ref(false);
const sourceDoc = ref<JSONContent>(createEmptyWorkspaceSourceDoc());
const currentViewDoc = ref<JSONContent>(createEmptyWorkspaceSourceDoc());
const layoutMode = ref<WorkspaceEditorLayoutMode>("list");
const restoredSessionKey = ref<string | null>(null);
const sourceDocSessionKey = ref<string | null>(null);
const editingSourceDocBaseline = ref<JSONContent | null>(null);
const compositionLayoutHints = ref<WorkspaceCompositionLayoutHints | null>(null);
const editingCompositionLayoutHintsBaseline =
  ref<WorkspaceCompositionLayoutHints | null>(null);
const sourceDocRevision = ref(0);
const edgeTopologyRevision = ref(0);
const layoutHintRevision = ref(0);
const editNormalizationError = ref<string | null>(null);
const renderMap = ref<ReturnType<typeof extractRenderMapFromDoc> | null>(null);
const editorRef = ref<{ editor: any } | null>(null);
const canvasRef = ref<HTMLElement | null>(null);
const editorSelectionHint = ref({
  visible: false,
  message: EDITOR_TERMINAL_HINT_MESSAGE,
  x: 0,
  y: 0,
});
const lastSessionSegments = ref<
  Array<
    Pick<
      EditableSegment,
      | "segment_id"
      | "order_key"
      | "terminal_raw"
      | "terminal_closer_suffix"
      | "terminal_source"
      | "detected_language"
    > & { display_text: string }
  >
>([]);
const lastSessionEdges = ref<EditableEdge[]>([]);

let draftPersistTimeoutId: number | null = null;
let lastPersistKey: string | null = null;
let lastAppliedViewKey: string | null = null;
let sourceDocSerialized = JSON.stringify(sourceDoc.value);
let compositionLayoutHintsSerialized = JSON.stringify(compositionLayoutHints.value);
let editorSelectionHintHideTimeoutId: number | null = null;
let lastEditorSelectionHintAt = 0;

const sessionSegments = computed<EditableSegment[]>(() =>
  resolveWorkspaceSessionItems({
    snapshotDocumentVersion: editSession.snapshot.value?.document_version,
    currentDocumentVersion: currentDocumentVersion.value,
    snapshotItems: editSession.snapshot.value?.segments,
    liveItems: editSession.segments.value,
  }),
);

const sortedReadySegments = computed(() =>
  [...sessionSegments.value].sort((left, right) => left.order_key - right.order_key),
);

const sessionEdges = computed<EditableEdge[]>(() =>
  resolveWorkspaceSessionItems({
    snapshotDocumentVersion: editSession.snapshot.value?.document_version,
    currentDocumentVersion: currentDocumentVersion.value,
    snapshotItems: editSession.snapshot.value?.edges,
    liveItems: editSession.edges.value,
  }),
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
const currentWorkingText = computed(() => extractWorkspaceEffectiveText(sourceDoc.value));
const currentSessionSegmentIds = computed(() =>
  sortedReadySegments.value.map((segment) => segment.segment_id),
);
const workspaceEdges = computed<WorkspaceSemanticEdge[]>(() =>
  sessionEdges.value.map((edge) => ({
    edgeId: edge.edge_id,
    leftSegmentId: edge.left_segment_id,
    rightSegmentId: edge.right_segment_id,
    pauseDurationSeconds: edge.pause_duration_seconds,
    boundaryStrategy: edge.boundary_strategy,
  })),
);
const backendSegmentTextById = computed<Record<string, string>>(() =>
  Object.fromEntries(
    sortedReadySegments.value.map((segment) => [
      segment.segment_id,
      buildSegmentDisplayText(segment),
    ]),
  ),
);
const backendSegmentDraftById = computed<Record<string, WorkspaceSegmentTextDraft>>(() =>
  Object.fromEntries(
    sortedReadySegments.value.map((segment) => [
      segment.segment_id,
      {
        segmentId: segment.segment_id,
        stem: segment.stem,
        terminal_raw: segment.terminal_raw ?? "",
        terminal_closer_suffix: segment.terminal_closer_suffix ?? "",
        terminal_source: segment.terminal_source ?? "synthetic",
      },
    ]),
  ),
);
const pendingRerenderTargets = computed(() =>
  resolveRerenderTargets({
    dirtyTextSegmentIds: lightEdit.dirtySegmentIds.value,
    segments: editSession.segments.value.map((segment) => ({
      segment_id: segment.segment_id,
      order_key: segment.order_key,
      render_status: segment.render_status,
    })),
  }),
);
const committedOrder = computed(() =>
  sortedReadySegments.value.map((segment) => segment.segment_id),
);
const hasReorderDraft = computed(() => reorderDraft.hasDraft.value);

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

function areSegmentDraftsEqual(
  left: WorkspaceSegmentTextDraft,
  right: WorkspaceSegmentTextDraft,
) {
  return left.stem === right.stem &&
    left.terminal_raw === right.terminal_raw &&
    left.terminal_closer_suffix === right.terminal_closer_suffix &&
    left.terminal_source === right.terminal_source;
}

function getSessionSegmentById(segmentId: string): EditableSegment | undefined {
  return sortedReadySegments.value.find((segment) => segment.segment_id === segmentId);
}

function buildDisplayTextForDraft(
  segmentId: string,
  draft: WorkspaceSegmentTextDraft,
): string {
  const segment = getSessionSegmentById(segmentId);
  return buildWorkspaceSegmentDisplayTextFromDraft({
    draft,
    detectedLanguage: segment?.detected_language ?? null,
    textLanguage: segment?.text_language ?? null,
  });
}

const sourceDocSegmentDraftEntries = computed<WorkspaceSegmentTextDraft[]>(() => {
  if (
    editSession.sessionStatus.value !== "ready" ||
    currentSessionKey.value === null ||
    sourceDocSessionKey.value !== currentSessionKey.value
  ) {
    return sortedReadySegments.value.map((segment) => ({
      segmentId: segment.segment_id,
      stem: segment.stem,
      terminal_raw: segment.terminal_raw ?? "",
      terminal_closer_suffix: segment.terminal_closer_suffix ?? "",
      terminal_source: segment.terminal_source ?? "synthetic",
    }));
  }

  return extractOrderedSegmentDraftsFromWorkspaceViewDoc(
    sourceDoc.value,
    currentSessionSegmentIds.value,
    backendSegmentDraftById.value,
  );
});

const sourceDocSegmentTexts = computed(() =>
  sourceDocSegmentDraftEntries.value.map((draft, index) => ({
    segmentId: draft.segmentId,
    orderKey: sortedReadySegments.value[index]?.order_key ?? index + 1,
    text: buildDisplayTextForDraft(draft.segmentId, draft),
  })),
);

const listReorder = useWorkspaceListReorder({
  canStartDrag() {
    return (
      !reorderDraft.isSubmitting.value &&
      (canStartFreshReorder.value || hasReorderDraft.value)
    );
  },
  getCurrentOrder() {
    return displayOrder.value;
  },
  getCommittedOrder() {
    return committedOrder.value;
  },
  getScrollContainer() {
    return canvasRef.value;
  },
  onStage({ nextOrder, committedOrder: nextCommittedOrder }) {
    return reorderDraft.setStagedOrder(nextOrder, nextCommittedOrder);
  },
});

const sourceDocSegmentDrafts = computed<Record<string, WorkspaceSegmentTextDraft>>(() =>
  Object.fromEntries(
    sourceDocSegmentDraftEntries.value
      .filter((draft) => !areSegmentDraftsEqual(
        draft,
        backendSegmentDraftById.value[draft.segmentId] ??
          createEmptyWorkspaceSegmentTextDraft(draft.segmentId),
      ))
      .map((draft) => [draft.segmentId, draft]),
  ),
);

const displayOrder = computed(
  () =>
    reorderDraft.stagedOrder.value ?? committedOrder.value,
);

const displaySegmentTexts = computed(() => {
  const textBySegmentId = new Map(
    sourceDocSegmentTexts.value.map((segment) => [segment.segmentId, segment.text]),
  );

  return displayOrder.value.map((segmentId, index) => ({
    segmentId,
    orderKey: index + 1,
    text: textBySegmentId.get(segmentId) ?? backendSegmentTextById.value[segmentId] ?? "",
  }));
});

const displayWorkspaceEdges = computed(() =>
  buildDisplayWorkspaceEdges({
    orderedSegmentIds: displayOrder.value,
    edges: workspaceEdges.value,
  }),
);

const semanticDocument = computed(() => {
  if (editSession.sessionStatus.value === "ready") {
    return buildWorkspaceSemanticDocument({
      sourceText: editSession.sourceText.value,
      compositionLayoutHints: compositionLayoutHints.value,
      segments: displaySegmentTexts.value.map((segment) => ({
        segmentId: segment.segmentId,
        orderKey: segment.orderKey,
        text: segment.text,
        renderStatus: "completed",
      })),
      edges: displayWorkspaceEdges.value,
      dirtySegmentIds: new Set(Object.keys(sourceDocSegmentDrafts.value)),
    });
  }

  if (runtimeState.isInitialRendering.value) {
    return buildWorkspaceSemanticDocument({
      sourceText: editSession.sourceText.value,
      segments: runtimeState.progressiveSegments.value.map((segment) => ({
        segmentId: segment.segmentId,
        orderKey: segment.orderKey,
        text: segment.displayText,
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
const canStartFreshReorder = computed(() =>
  canStartListReorder({
    layoutMode: effectiveLayoutMode.value,
    isEditing: isEditing.value,
    sessionStatus: editSession.sessionStatus.value,
    hasTextDraft: lightEdit.dirtyCount.value > 0,
    hasParameterDraft: parameterPanel.hasDirty.value,
    hasPendingRerender: pendingRerenderTargets.value.count > 0,
    canMutate: runtimeState.canMutate.value,
    isInteractionLocked: workspaceProcessing.isInteractionLocked.value,
  }),
);
const renderPlan = computed(() =>
  buildWorkspaceRenderPlan(semanticDocument.value, effectiveLayoutMode.value),
);

const orderedSegmentIds = computed(
  () => renderPlan.value.renderMap.orderedSegmentIds,
);
const segmentCount = computed(() => orderedSegmentIds.value.length);
const modeLabel = computed(() => (isEditing.value ? "编辑态" : "展示态"));
const compositionAvailable = computed(
  () => semanticDocument.value.compositionAvailability.ready,
);
const isInteractionLocked = computed(
  () => workspaceProcessing.isInteractionLocked.value,
);
const autoPlayButtonTitle = computed(() =>
  isAutoPlayEnabled.value
    ? "开启后，单击段时自动跳转并播放"
    : "关闭后，单击段时只更新选择",
);
const activeViewKey = computed(() =>
  buildWorkspaceViewRevisionKey({
    layoutMode: effectiveLayoutMode.value,
    sourceDocRevision: sourceDocRevision.value,
    edgeTopologyRevision: edgeTopologyRevision.value,
    layoutHintRevision: layoutHintRevision.value,
  }),
);
const displayViewKey = computed(() => {
  const previewSignature = reorderDraft.stagedOrder.value?.join("|") ?? "base";
  return `${activeViewKey.value}:${previewSignature}`;
});
const dragGhostText = computed(() => {
  const draggingId = listReorder.draggingSegmentId.value;
  if (!draggingId) {
    return "";
  }

  return (
    sourceDocSegmentTexts.value.find((segment) => segment.segmentId === draggingId)?.text ??
    backendSegmentTextById.value[draggingId] ??
    ""
  );
});
const dragGhostLineNumber = computed(() => {
  const draggingId = listReorder.draggingSegmentId.value;
  if (!draggingId) {
    return null;
  }

  const order = displayOrder.value;
  const index = order.indexOf(draggingId);
  return index >= 0 ? index + 1 : null;
});
const dragGhostStyle = computed<Record<string, string>>(() => {
  if (
    listReorder.pointerClientX.value === null ||
    listReorder.pointerClientY.value === null
  ) {
    return {};
  }

  return {
    left: `${listReorder.pointerClientX.value + 18}px`,
    top: `${listReorder.pointerClientY.value + 16}px`,
  };
});

const customExtensions = buildEditorExtensions({
  onActivateEdge(edgeId) {
    activateEdgeSelection(edgeId);
  },
  onProtectedTerminalCapsule() {
    showEditorSelectionHint();
  },
});

// ── 右键菜单状态 ──

const contextMenu = ref({ visible: false, x: 0, y: 0, segmentId: null as string | null });

const segmentDeletionGuard = computed(() =>
  resolveSegmentDeletionGuard({
    segmentCount: sortedReadySegments.value.length,
    canMutate: runtimeState.canMutate.value,
    isInteractionLocked: isInteractionLocked.value,
    hasTextDraft: lightEdit.dirtyCount.value > 0,
    hasParameterDraft: parameterPanel.hasDirty.value,
    hasPendingRerender: pendingRerenderTargets.value.count > 0,
    hasReorderDraft: hasReorderDraft.value,
  }),
);

const canDeleteFromMenu = computed(() => segmentDeletionGuard.value.allowed);
const unregisterWorkspaceExitHandlers = registerWorkspaceExitHandlers({
  hasPendingTextChanges: () => lightEdit.dirtyCount.value > 0,
  flushDraft: () => {
    clearPendingDraftPersist();
    if (lightEdit.dirtyCount.value === 0) {
      return;
    }
    persistWorkspaceDraftSnapshot(
      isEditing.value ? "editing" : "preview",
      currentViewDoc.value,
    );
  },
  clearDraft: () => {
    clearPendingDraftPersist();
    clearPersistedWorkspaceDraft();
  },
});

function clearPendingDraftPersist() {
  if (draftPersistTimeoutId === null) {
    return;
  }

  window.clearTimeout(draftPersistTimeoutId);
  draftPersistTimeoutId = null;
}

function hideEditorSelectionHint() {
  if (editorSelectionHintHideTimeoutId !== null) {
    window.clearTimeout(editorSelectionHintHideTimeoutId);
    editorSelectionHintHideTimeoutId = null;
  }
  editorSelectionHint.value.visible = false;
}

function resolveEditorSelectionHintAnchor() {
  const editor = editorRef.value?.editor;
  if (!editor) {
    return null;
  }

  const { selection } = editor.state;
  const anchorPos = Math.max(0, Math.min(selection.to, editor.state.doc.content.size));
  const coords = editor.view.coordsAtPos(anchorPos);
  return {
    x: Math.round((coords.left + coords.right) / 2),
    y: Math.round(coords.bottom + 10),
  };
}

function showEditorSelectionHint(anchor = resolveEditorSelectionHintAnchor()) {
  if (!anchor) {
    return;
  }

  const now = Date.now();
  if (
    editorSelectionHint.value.visible &&
    now - lastEditorSelectionHintAt < EDITOR_TERMINAL_HINT_THROTTLE_MS
  ) {
    return;
  }

  lastEditorSelectionHintAt = now;
  editorSelectionHint.value = {
    visible: true,
    message: EDITOR_TERMINAL_HINT_MESSAGE,
    x: anchor.x,
    y: anchor.y,
  };

  if (editorSelectionHintHideTimeoutId !== null) {
    window.clearTimeout(editorSelectionHintHideTimeoutId);
  }
  editorSelectionHintHideTimeoutId = window.setTimeout(() => {
    editorSelectionHintHideTimeoutId = null;
    editorSelectionHint.value.visible = false;
  }, EDITOR_TERMINAL_HINT_HIDE_MS);
}

function ensureNoReorderDraft() {
  if (!hasReorderDraft.value) {
    return true;
  }

  ElMessage.warning(REORDER_DRAFT_LOCK_MESSAGE);
  return false;
}

function discardReorderDraft(showMessage = false) {
  if (!hasReorderDraft.value) {
    return;
  }

  reorderDraft.clearDraft();
  listReorder.resetState();
  if (showMessage) {
    ElMessage.info("已放弃当前顺序调整");
  }
}

async function applyReorderDraft() {
  const stagedOrder = reorderDraft.stagedOrder.value;
  if (!stagedOrder || stagedOrder.length === 0) {
    return;
  }
  if (currentDocumentVersion.value === null) {
    ElMessage.error("当前文档版本缺失，无法应用顺序调整");
    throw new Error("missing_document_version");
  }

  reorderDraft.startSubmitting();
  try {
    const job = await reorderSegments({
      base_document_version: currentDocumentVersion.value,
      ordered_segment_ids: stagedOrder,
    });
    runtimeState.trackJob(job, {
      refreshSessionOnTerminal: true,
    });
    const terminalStatus = await runtimeState.waitForJobTerminal(job.job_id);
    await editSession.refreshFormalSessionState();

    if (terminalStatus !== "completed") {
      throw new Error(`reorder_failed:${terminalStatus}`);
    }

    discardReorderDraft();
    ElMessage.success("顺序调整已应用");
  } catch (error) {
    try {
      await editSession.refreshFormalSessionState();
    } catch (refreshError) {
      console.error("刷新重排后的正式会话状态失败", refreshError);
    }

    discardReorderDraft();
    ElMessage.error("顺序调整应用失败，已恢复正式顺序");
    throw error;
  } finally {
    reorderDraft.finishSubmitting();
  }
}

const unregisterReorderDraftActions = reorderDraft.registerActions({
  applyDraft: applyReorderDraft,
  discardDraft: () => discardReorderDraft(true),
});

function handleGlobalKeyDown(event: KeyboardEvent) {
  if (event.key === " " && !isEditing.value && !isInteractionLocked.value) {
    const activeElement = document.activeElement as HTMLElement | null;
    const activeTag = activeElement?.tagName.toLowerCase();
    const isInputArea = activeTag === "input" || activeTag === "textarea" || activeElement?.isContentEditable;

    if (!isInputArea) {
      event.preventDefault(); // 阻止空格键导致的页面滚动
      event.stopPropagation();
      if (isPlaying.value) {
        pause();
      } else {
        play();
      }
    }
  }
}

onMounted(() => {
  window.addEventListener("keydown", handleGlobalKeyDown);
});

onBeforeUnmount(() => {
  window.removeEventListener("keydown", handleGlobalKeyDown);
  clearPendingDraftPersist();
  hideEditorSelectionHint();
  unregisterWorkspaceExitHandlers();
  unregisterReorderDraftActions();
});

function buildSegmentDraftRecord(
  drafts: Record<string, WorkspaceSegmentTextDraft> = sourceDocSegmentDrafts.value,
): Record<string, WorkspaceSegmentTextDraft> {
  return Object.fromEntries(
    Object.entries(drafts).map(([segmentId, draft]) => [
      segmentId,
      { ...draft },
    ]),
  );
}

function setSourceDoc(nextDoc: JSONContent) {
  const nextSerialized = JSON.stringify(nextDoc);
  if (nextSerialized === sourceDocSerialized) {
    return false;
  }

  sourceDoc.value = nextDoc;
  sourceDocSerialized = nextSerialized;
  sourceDocRevision.value += 1;
  lastAppliedViewKey = null;
  return true;
}

function setCompositionLayoutHints(
  nextHints: WorkspaceCompositionLayoutHints | null,
) {
  const nextSerialized = JSON.stringify(nextHints);
  if (nextSerialized === compositionLayoutHintsSerialized) {
    return false;
  }

  compositionLayoutHints.value = nextHints;
  compositionLayoutHintsSerialized = nextSerialized;
  layoutHintRevision.value += 1;
  lastAppliedViewKey = null;
  return true;
}

function resolveSourceTextStatus(
  reason: string | null,
): WorkspaceCompositionLayoutHints["sourceTextStatus"] {
  if (reason === "missing_source_text") {
    return "missing";
  }

  return reason === null ? "aligned" : "detached";
}

function buildWorkingCopyCompositionLayoutHints(): WorkspaceCompositionLayoutHints {
  return {
    basis: "working_copy",
    segmentIdsByBlock:
      currentSessionSegmentIds.value.length > 0
        ? [[...currentSessionSegmentIds.value]]
        : [],
    sourceTextStatus: editSession.sourceText.value ? "detached" : "missing",
  };
}

function syncCompositionLayoutHintsFromSemanticDocument() {
  setCompositionLayoutHints(buildCompositionLayoutHintsFromSourceBlocks({
    sourceBlocks: semanticDocument.value.sourceBlocks,
    basis:
      semanticDocument.value.compositionAvailability.reason === null
        ? "source_text"
        : "working_copy",
    sourceTextStatus: resolveSourceTextStatus(
      semanticDocument.value.compositionAvailability.reason,
    ),
  }));
}

function updateCompositionLayoutHintsForEditingView(viewDoc: JSONContent) {
  if (effectiveLayoutMode.value === "composition") {
    setCompositionLayoutHints(buildCompositionLayoutHintsFromViewDoc({
      viewDoc,
      basis: "working_copy",
      sourceTextStatus: editSession.sourceText.value ? "detached" : "missing",
    }));
    return;
  }

  if (
    areCompositionLayoutHintsCompatible(
      compositionLayoutHints.value,
      currentSessionSegmentIds.value,
    )
  ) {
    return;
  }

  setCompositionLayoutHints(buildWorkingCopyCompositionLayoutHints());
}

function syncEditingSourceState(viewDoc: JSONContent): boolean {
  try {
    setSourceDoc(normalizeWorkspaceViewDocToSourceDoc({
      viewDoc,
      orderedSegmentIds: currentSessionSegmentIds.value,
      edges: workspaceEdges.value,
      previousDraftsBySegmentId: Object.fromEntries(
        sourceDocSegmentDraftEntries.value.map((draft) => [draft.segmentId, draft]),
      ),
    }));
    sourceDocSessionKey.value = currentSessionKey.value;
    updateCompositionLayoutHintsForEditingView(viewDoc);
    editNormalizationError.value = null;
    return true;
  } catch (error) {
    editNormalizationError.value =
      error instanceof Error ? error.message : "正文结构异常，暂时无法同步编辑结果";
    return false;
  }
}

function persistWorkspaceDraftSnapshot(
  mode: WorkspaceDraftMode,
  editorDoc: JSONContent,
  segmentDrafts: Record<string, WorkspaceSegmentTextDraft> = buildSegmentDraftRecord(),
) {
  if (!currentDocumentId.value || currentDocumentVersion.value === null) {
    return;
  }

  const persistKey = buildWorkspaceDraftPersistKey({
    documentVersion: currentDocumentVersion.value,
    mode,
    sourceDocRevision: sourceDocRevision.value,
    layoutHintRevision: layoutHintRevision.value,
  });
  const scopedPersistKey = `${currentDocumentId.value}:${persistKey}`;
  if (lastPersistKey === scopedPersistKey) {
    return;
  }

  const saved = workspaceDraftPersistence.saveSnapshot({
    schemaVersion: WORKSPACE_DRAFT_SCHEMA_VERSION,
    documentId: currentDocumentId.value,
    documentVersion: currentDocumentVersion.value,
    segmentIds: [...currentSessionSegmentIds.value],
    mode,
    editorDoc,
    sourceDoc: sourceDoc.value,
    segmentDrafts,
    effectiveText: extractWorkspaceEffectiveText(sourceDoc.value),
    compositionLayoutHints: compositionLayoutHints.value,
    updatedAt: new Date().toISOString(),
  });
  if (saved) {
    lastPersistKey = scopedPersistKey;
  }
}

function clearPersistedWorkspaceDraft() {
  if (!currentDocumentId.value) {
    return;
  }

  lastPersistKey = null;
  workspaceDraftPersistence.clearSnapshot(currentDocumentId.value);
}

function syncPreviewWorkspaceState(editorDoc: JSONContent) {
  if (hasReorderDraft.value) {
    return;
  }

  if (lightEdit.dirtyCount.value === 0) {
    clearPersistedWorkspaceDraft();
    return;
  }

  persistWorkspaceDraftSnapshot("preview", editorDoc);
}

function pushContentToEditor(
  editorOverride?: any,
  docOverride: JSONContent = currentViewDoc.value,
  viewKeyOverride: string = displayViewKey.value,
  force = false,
) {
  nextTick(() => {
    const editor = editorOverride ?? editorRef.value?.editor;
    if (!editor) {
      return;
    }

    if (!force && lastAppliedViewKey === viewKeyOverride) {
      return;
    }

    editor.commands.setContent(docOverride);
    lastAppliedViewKey = viewKeyOverride;
    renderMap.value = extractRenderMapFromDoc(
      editor.getJSON(),
      renderPlan.value.renderMap.orderedSegmentIds,
      effectiveLayoutMode.value,
    );
    syncDecorationState(editor);
  });
}

function syncDisplayDocument(force = false) {
  if (isEditing.value) {
    return;
  }

  currentViewDoc.value = renderPlan.value.doc;
  pushContentToEditor(undefined, renderPlan.value.doc, displayViewKey.value, force);

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
    showReorderHandle: canStartFreshReorder.value,
    playingId:
      currentCursor.value?.kind === "segment"
        ? currentCursor.value.segmentId
        : null,
    playingCursor: currentCursor.value,
    selectedIds: segmentSelection.selectedSegmentIds.value,
    dirtyIds: lightEdit.dirtySegmentIds.value,
    dirtyEdgeIds: parameterPanel.dirtyEdgeIds.value,
    isEditing: isEditing.value,
    draggingSegmentId: listReorder.draggingSegmentId.value,
    dropTargetSegmentId: listReorder.dropTargetSegmentId.value,
    dropIntent: listReorder.dropIntent.value,
    isSubmittingReorder: reorderDraft.isSubmitting.value,
  };

  editor.view.dispatch(editor.state.tr.setMeta(segmentDecorationKey, true));
}

function isEditorSnapshotCompatible(editorDoc: JSONContent): boolean {
  if (currentSessionSegmentIds.value.length === 0) {
    return true;
  }

  try {
    extractOrderedSegmentDraftsFromWorkspaceViewDoc(
      editorDoc,
      currentSessionSegmentIds.value,
      backendSegmentDraftById.value,
    );
    return true;
  } catch {
    return false;
  }
}

function requestNextLayoutMode(nextMode: WorkspaceEditorLayoutMode) {
  if (!ensureNoReorderDraft()) {
    return;
  }

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
  const segment = sortedReadySegments.value.find(
    (item) => item.segment_id === segmentId,
  );
  return segment ? buildSegmentDisplayText(segment) : "";
}

function getBackendSegmentDraft(segmentId: string): WorkspaceSegmentTextDraft {
  return backendSegmentDraftById.value[segmentId] ??
    createEmptyWorkspaceSegmentTextDraft(segmentId);
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
  pushContentToEditor(editor, currentViewDoc.value, displayViewKey.value, true);
}

function enterEditMode(clickEvent?: MouseEvent) {
  if (isEditing.value) {
    return;
  }
  if (!ensureNoReorderDraft()) {
    return;
  }
  if (isInteractionLocked.value) {
    ElMessage.warning("当前正在处理正式结果，暂时不能编辑正文");
    return;
  }

  segmentSelection.clearSelection();
  editingSourceDocBaseline.value = cloneWorkspaceSerializable(sourceDoc.value);
  editingCompositionLayoutHintsBaseline.value = compositionLayoutHints.value
    ? cloneWorkspaceSerializable(compositionLayoutHints.value)
    : null;
  editNormalizationError.value = null;
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

function commitEditWithDoc(editorDoc: JSONContent) {
  try {
    const nextSourceDoc = normalizeWorkspaceViewDocToSourceDoc({
      viewDoc: editorDoc,
      orderedSegmentIds: currentSessionSegmentIds.value,
      edges: workspaceEdges.value,
      previousDraftsBySegmentId: Object.fromEntries(
        sourceDocSegmentDraftEntries.value.map((draft) => [draft.segmentId, draft]),
      ),
    });
    const nextDrafts = Object.fromEntries(
      extractOrderedSegmentDraftsFromWorkspaceViewDoc(
        nextSourceDoc,
        currentSessionSegmentIds.value,
        backendSegmentDraftById.value,
      )
        .filter((draft) => !areSegmentDraftsEqual(
          draft,
          getBackendSegmentDraft(draft.segmentId),
        ))
        .map((draft) => [draft.segmentId, draft]),
    );

    clearPendingDraftPersist();
    currentViewDoc.value = editorDoc;
    setSourceDoc(nextSourceDoc);
    sourceDocSessionKey.value = currentSessionKey.value;
    updateCompositionLayoutHintsForEditingView(editorDoc);
    lightEdit.replaceAllDrafts(nextDrafts);

    if (Object.keys(nextDrafts).length > 0) {
      persistWorkspaceDraftSnapshot("preview", editorDoc, nextDrafts);
    } else {
      clearPersistedWorkspaceDraft();
    }
  } catch (error) {
    ElMessage.error(
      error instanceof Error ? error.message : "正文结构异常，无法提交编辑",
    );
    return false;
  }

  editingSourceDocBaseline.value = null;
  editingCompositionLayoutHintsBaseline.value = null;
  isEditing.value = false;
  nextTick(syncDisplayDocument);
  return true;
}

async function waitForDeleteJobCompletion(segmentId: string) {
  const job = await deleteSegment(segmentId);
  runtimeState.trackJob(job, { refreshSessionOnTerminal: false });
  const terminalStatus = await runtimeState.waitForJobTerminal(job.job_id);
  if (terminalStatus !== "completed") {
    throw new Error(`delete_failed:${terminalStatus}`);
  }
}

async function commitAndExitEdit() {
  const editor = editorRef.value?.editor;
  if (!editor) {
    clearPendingDraftPersist();
    editingSourceDocBaseline.value = null;
    editingCompositionLayoutHintsBaseline.value = null;
    isEditing.value = false;
    nextTick(syncDisplayDocument);
    return;
  }

  const editorDoc = editor.getJSON();

  // ── 编辑态删段检测 ──
  const candidates = effectiveLayoutMode.value === "list"
    ? detectDeletionCandidates(editorDoc, currentSessionSegmentIds.value)
    : [];
  if (candidates.length > 0) {
    if (candidates.length >= currentSessionSegmentIds.value.length) {
      ElMessage.warning("至少保留一段");
      return;
    }

    let confirmed = false;
    try {
      confirmed = await confirmSegmentDeletion(candidates.length);
    } catch (error) {
      ElMessage.error(
        error instanceof Error ? error.message : "删段确认框打开失败",
      );
      return;
    }

    const restorations = candidates.map((id) => ({
      segmentId: id,
      originalDraft: getBackendSegmentDraft(id),
      detectedLanguage: getSessionSegmentById(id)?.detected_language ?? null,
      textLanguage: getSessionSegmentById(id)?.text_language ?? null,
    }));
    const patchedDoc = patchEditorDocForRestoredSegments(
      editorDoc, currentSessionSegmentIds.value, restorations,
    );
    editor.commands.setContent(patchedDoc);

    if (!confirmed) {
      // 用户选择不删除 — 段文字已回退，留在编辑态
      syncEditingSourceState(patchedDoc);
      return;
    }

    // 用户确认删除 — 先用修补后 doc 正常提交，再调 API 删段
    if (!commitEditWithDoc(patchedDoc)) {
      return;
    }

    const deletionResult = await runDeletionJobs({
      segmentIds: candidates,
      deleteSegment: waitForDeleteJobCompletion,
    });

    await editSession.refreshFormalSessionState();
    segmentSelection.clearSelection();
    for (const id of deletionResult.deletedSegmentIds) {
      lightEdit.clearDraft(id);
    }
    if (!deletionResult.completed) {
      ElMessage.error(
        `删除段失败，已成功删除 ${deletionResult.deletedSegmentIds.length} 段，失败段为 ${deletionResult.failedSegmentId ?? "unknown"}`,
      );
      return;
    }
    ElMessage.success("已删除清空的段");
    return;
  }

  // ── 无删段意图 — 正常提交 ──
  commitEditWithDoc(editorDoc);
}

function discardAndExitEdit() {
  clearPendingDraftPersist();
  if (editingSourceDocBaseline.value) {
    setSourceDoc(editingSourceDocBaseline.value);
    sourceDocSessionKey.value = currentSessionKey.value;
  }
  setCompositionLayoutHints(editingCompositionLayoutHintsBaseline.value);
  editingSourceDocBaseline.value = null;
  editingCompositionLayoutHintsBaseline.value = null;
  editNormalizationError.value = null;
  isEditing.value = false;
  nextTick(syncDisplayDocument);
}

function handleResetSessionSuccess() {
  segmentSelection.clearSelection();
  lightEdit.clearAll();
  reorderDraft.clearDraft();
  listReorder.resetState();
  clearPendingDraftPersist();
  editingSourceDocBaseline.value = null;
  editingCompositionLayoutHintsBaseline.value = null;
  setCompositionLayoutHints(null);
  editNormalizationError.value = null;
  isEditing.value = false;
  nextTick(syncDisplayDocument);
}

async function finalizeEndSession(choice: EndSessionChoice) {
  const result = resolveEndSessionChoiceResult({
    choice,
    appliedText: currentSessionHeadText.value ?? "",
    workingText: currentWorkingText.value,
  });

  if (!result.shouldEndSession) {
    endSessionDialogVisible.value = false;
    return;
  }

  try {
    isEndingSession.value = true;
    let endSessionTarget =
      result.nextInputSource !== null && result.nextInputText !== null
        ? {
            nextInputText: result.nextInputText,
            nextInputSource: result.nextInputSource,
          }
        : undefined;

    if (result.shouldApplyUpdatesBeforeEndSession) {
      try {
        await applyReorderDraft();
      } catch {
        return;
      }
      endSessionTarget = {
        nextInputText: buildSessionHeadText(sortedReadySegments.value),
        nextInputSource: "applied_text",
      };
    }

    await editSession.endSession(
      endSessionTarget,
    );
    parameterPanel.discardDraft();
    handleResetSessionSuccess();
    endSessionDialogVisible.value = false;
    ElMessage.success("当前会话已结束");
  } catch (error) {
    ElMessage.error(
      error instanceof Error ? error.message : "结束当前会话失败",
    );
  } finally {
    isEndingSession.value = false;
  }
}

async function requestEndSession() {
  endSessionDialogMode.value = resolveEndSessionGuard({
    hasPendingTextChanges: lightEdit.dirtyCount.value > 0,
    hasPendingRerender: pendingRerenderTargets.value.count > 0,
    hasDirtyParameterDraft: parameterPanel.hasDirty.value,
    hasPendingReorderDraft: hasReorderDraft.value,
  });
  endSessionDialogVisible.value = true;
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

  const nextDoc = value;
  currentViewDoc.value = nextDoc;
  clearPendingDraftPersist();
  if (!syncEditingSourceState(nextDoc)) {
    return;
  }
  draftPersistTimeoutId = window.setTimeout(() => {
    draftPersistTimeoutId = null;
    persistWorkspaceDraftSnapshot("editing", nextDoc);
  }, WORKSPACE_DRAFT_SAVE_DEBOUNCE_MS);
}

function onCanvasPointerDown(event: PointerEvent) {
  const handleSegmentId = findReorderHandleTarget(event.target as any);
  if (!handleSegmentId) {
    return;
  }

  if (listReorder.startCandidateDrag(event, handleSegmentId)) {
    segmentSelection.select(handleSegmentId);
  }
}

let clickPlayTimer: ReturnType<typeof setTimeout> | null = null;

function scheduleSegmentAutoPlay(segmentId: string) {
  if (!isAutoPlayEnabled.value) {
    return;
  }

  if (clickPlayTimer !== null) {
    clearTimeout(clickPlayTimer);
    clickPlayTimer = null;
  }

  clickPlayTimer = setTimeout(() => {
    clickPlayTimer = null;
    if (isEditing.value || !isAutoPlayEnabled.value) return;
    seekToSegment(segmentId);
    play();
  }, 250);
}

function onCanvasClick(event: MouseEvent) {
  if (listReorder.consumeClickSuppression()) {
    event.preventDefault();
    event.stopPropagation();
    return;
  }

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
    activateEdgeSelection(target.edgeId);
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

  const segmentId = target.segmentId;
  scheduleSegmentAutoPlay(segmentId);
}

function onCanvasDblClick(event: MouseEvent) {
  if (clickPlayTimer !== null) {
    clearTimeout(clickPlayTimer);
    clickPlayTimer = null;
  }

  if (listReorder.consumeClickSuppression()) {
    event.preventDefault();
    event.stopPropagation();
    return;
  }

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

function activateEdgeSelection(edgeId: string | null) {
  if (isEditing.value || !edgeId) {
    return;
  }

  if (
    shouldBlockEdgeEditing({
      edgeId,
      edges: sessionEdges.value,
      dirtySegmentIds: lightEdit.dirtySegmentIds.value,
    })
  ) {
    ElMessage.warning("该停顿会影响待重推理段，请先重推理");
    return;
  }

  segmentSelection.selectEdge(edgeId);
}

// ── 右键菜单与删段 ──

function onCanvasContextMenu(event: MouseEvent) {
  if (isEditing.value) {
    return;
  }

  const target = findCanvasTarget(event.target as any);
  if (target?.type !== "segment" || !target.segmentId) {
    return;
  }

  event.preventDefault();
  segmentSelection.select(target.segmentId);
  if (!segmentDeletionGuard.value.allowed) {
    if (segmentDeletionGuard.value.reason) {
      ElMessage.warning(segmentDeletionGuard.value.reason);
    }
    closeContextMenu();
    return;
  }
  contextMenu.value = {
    visible: true,
    x: event.clientX,
    y: event.clientY,
    segmentId: target.segmentId,
  };
}

function closeContextMenu() {
  contextMenu.value = {
    visible: false,
    x: 0,
    y: 0,
    segmentId: null,
  };
}

async function executeDeleteSegment(segmentId: string) {
  closeContextMenu();
  if (!segmentDeletionGuard.value.allowed) {
    if (segmentDeletionGuard.value.reason) {
      ElMessage.warning(segmentDeletionGuard.value.reason);
    }
    return;
  }

  try {
    await ElMessageBox.confirm(
      "确定要删除这一段吗？",
      "删除段",
      {
        confirmButtonText: "删除",
        cancelButtonText: "取消",
        type: "warning",
        lockScroll: false,
      },
    );
  } catch (error) {
    if (error === "cancel" || error === "close") {
      return;
    }
    ElMessage.error(
      error instanceof Error ? error.message : "删除确认框打开失败",
    );
    return;
  }

  try {
    await waitForDeleteJobCompletion(segmentId);
    await editSession.refreshFormalSessionState();

    segmentSelection.clearSelection();
    lightEdit.clearDraft(segmentId);
    ElMessage.success("段已删除");
  } catch (err) {
    ElMessage.error(`删除失败: ${(err as Error).message}`);
  }
}

watch(
  currentSessionKey,
  (nextSessionKey, previousSessionKey) => {
    if (nextSessionKey !== previousSessionKey) {
      reorderDraft.clearDraft();
      listReorder.resetState();
    }

    if (!currentSessionKey.value) {
      restoredSessionKey.value = null;
      setSourceDoc(createEmptyWorkspaceSourceDoc());
      currentViewDoc.value = createEmptyWorkspaceSourceDoc();
      sourceDocSessionKey.value = null;
      editingSourceDocBaseline.value = null;
      editingCompositionLayoutHintsBaseline.value = null;
      setCompositionLayoutHints(null);
      lastPersistKey = null;
      lastSessionSegments.value = [];
      lastSessionEdges.value = [];
      return;
    }

    lastPersistKey = null;
    const snapshot = workspaceDraftPersistence.readCompatibleSnapshot({
      documentId: currentDocumentId.value!,
      documentVersion: currentDocumentVersion.value!,
      segmentIds: currentSessionSegmentIds.value,
    });

    clearPendingDraftPersist();
    if (snapshot) {
      setSourceDoc(snapshot.sourceDoc);
      sourceDocSessionKey.value = currentSessionKey.value;
      setCompositionLayoutHints(snapshot.compositionLayoutHints);
      if (snapshot.compositionLayoutHints === null) {
        syncCompositionLayoutHintsFromSemanticDocument();
      }
      lightEdit.replaceAllDrafts(snapshot.segmentDrafts);

      if (
        snapshot.mode === "editing" &&
        isEditorSnapshotCompatible(snapshot.editorDoc)
      ) {
        isEditing.value = true;
        editNormalizationError.value = null;
        editingSourceDocBaseline.value = cloneWorkspaceSerializable(snapshot.sourceDoc);
        editingCompositionLayoutHintsBaseline.value =
          snapshot.compositionLayoutHints
            ? cloneWorkspaceSerializable(snapshot.compositionLayoutHints)
            : null;
        currentViewDoc.value = snapshot.editorDoc;
        pushContentToEditor(undefined, snapshot.editorDoc, displayViewKey.value, true);
      } else {
        editingSourceDocBaseline.value = null;
        editingCompositionLayoutHintsBaseline.value = null;
        editNormalizationError.value = null;
        isEditing.value = false;
        syncDisplayDocument();
      }
    } else {
      if (
        shouldPreserveLocalTextDraftsOnVersionChange({
          previousSessionKey,
          nextSessionKey,
          isEditing: isEditing.value,
          dirtySegmentIds: lightEdit.dirtySegmentIds.value,
          previousSegments: lastSessionSegments.value,
          nextSegments: sortedReadySegments.value.map((segment) => ({
            segment_id: segment.segment_id,
            order_key: segment.order_key,
            display_text: buildSegmentDisplayText(segment),
          })),
          previousEdges: lastSessionEdges.value,
          nextEdges: sessionEdges.value,
        })
      ) {
        sourceDocSessionKey.value = currentSessionKey.value;
        editingSourceDocBaseline.value = null;
        editingCompositionLayoutHintsBaseline.value = null;
        editNormalizationError.value = null;
        isEditing.value = false;
        syncDisplayDocument();
      } else {
        setSourceDoc(buildWorkspaceSourceDoc({
          segments: sortedReadySegments.value.map((segment) => ({
            segmentId: segment.segment_id,
            orderKey: segment.order_key,
            stem: segment.stem,
            terminal_raw: segment.terminal_raw ?? "",
            terminal_closer_suffix: segment.terminal_closer_suffix ?? "",
            terminal_source: segment.terminal_source ?? "synthetic",
            detectedLanguage: segment.detected_language ?? null,
            textLanguage: segment.text_language ?? null,
          })),
          edges: workspaceEdges.value,
        }));
        sourceDocSessionKey.value = currentSessionKey.value;
        editingSourceDocBaseline.value = null;
        editingCompositionLayoutHintsBaseline.value = null;
        setCompositionLayoutHints(null);
        editNormalizationError.value = null;
        isEditing.value = false;
        syncCompositionLayoutHintsFromSemanticDocument();
        syncDisplayDocument();
      }
    }

    lastSessionSegments.value = sortedReadySegments.value.map((segment) => ({
      segment_id: segment.segment_id,
      order_key: segment.order_key,
      display_text: buildSegmentDisplayText(segment),
      terminal_raw: segment.terminal_raw,
      terminal_closer_suffix: segment.terminal_closer_suffix,
      terminal_source: segment.terminal_source,
      detected_language: segment.detected_language,
    }));
    lastSessionEdges.value = sessionEdges.value.map((edge) => ({ ...edge }));
    restoredSessionKey.value = currentSessionKey.value;
  },
  { immediate: true },
);

watch(
  sourceDocSegmentDrafts,
  (nextDrafts) => {
    lightEdit.replaceAllDrafts(nextDrafts);
  },
  { immediate: true, deep: true },
);

watch(
  [
    sourceDocSegmentTexts,
    () => reorderDraft.stagedOrder.value,
    () => listReorder.mode.value,
    () => runtimeState.progressiveSegments.value,
    () => editSession.sessionStatus.value,
    () => runtimeState.isInitialRendering.value,
  ],
  () => {
    if (!isEditing.value) {
      syncDisplayDocument(true);
    }
  },
  { immediate: true, deep: true },
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
  displayViewKey,
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
      edgeTopologyRevision.value += 1;
      lastAppliedViewKey = null;
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
    currentCursor,
    () => segmentSelection.selectedSegmentIds.value,
    () => lightEdit.dirtySegmentIds.value,
    () => parameterPanel.dirtyEdgeIds.value,
    isEditing,
    renderMap,
    hasReorderDraft,
    () => reorderDraft.isSubmitting.value,
    () => listReorder.mode.value,
    () => listReorder.draggingSegmentId.value,
    () => listReorder.dropTargetSegmentId.value,
    () => listReorder.dropIntent.value,
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
    pushContentToEditor(editor, currentViewDoc.value, displayViewKey.value, true);
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
      class="flex h-12 shrink-0 items-center justify-between border-b border-border/70 px-4 dark:border-border/30 relative"
    >
      <div class="flex min-w-0 items-center gap-2">
        <h3 class="text-sm font-semibold leading-none text-foreground">
          会话正文
        </h3>
        <div class="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">
          <span
            class="rounded px-2.5 py-1 text-xs font-medium leading-none"
            :class="isEditing
              ? 'border border-blue-400/20 bg-blue-50 text-blue-600 dark:bg-blue-900/20 dark:text-blue-400'
              : 'border border-border/50 bg-muted/50 text-muted-fg'"
          >
            {{ modeLabel }}
          </span>
        </div>
        <div class="inline-flex overflow-hidden rounded border border-border">
          <button
            type="button"
            class="px-2.5 py-1 text-xs transition-colors"
            :class="effectiveLayoutMode === 'list'
              ? 'bg-blue-500 text-white'
              : 'bg-transparent text-foreground'"
            :disabled="isEditing || isInteractionLocked"
            @click="requestNextLayoutMode('list')"
          >
            列表
          </button>
          <button
            type="button"
            class="px-2.5 py-1 text-xs transition-colors"
            :class="effectiveLayoutMode === 'composition'
              ? 'bg-blue-500 text-white'
              : 'bg-transparent text-foreground'"
            :disabled="isEditing || !compositionAvailable || isInteractionLocked"
            @click="requestNextLayoutMode('composition')"
          >
            组合
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
        <el-tooltip
          :content="autoPlayButtonTitle"
          placement="bottom"
        >
          <button
            type="button"
            class="rounded border px-2.5 py-1 text-xs font-medium transition-colors"
            :class="isAutoPlayEnabled
              ? 'border-blue-400/30 bg-blue-50 text-blue-600 hover:bg-blue-100/80 dark:border-blue-400/30 dark:bg-blue-900/20 dark:text-blue-400 dark:hover:bg-blue-900/30'
              : 'border-border text-muted-fg hover:bg-secondary/50'"
            :aria-pressed="isAutoPlayEnabled"
            :disabled="isInteractionLocked"
            @click="toggleAutoPlay()"
          >
            自动播放
          </button>
        </el-tooltip>

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
          :disabled="isEndingSession"
          @click="requestEndSession"
        >
          结束会话
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
      ref="canvasRef"
      class="flex-1 overflow-y-auto scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent"
      :class="effectiveLayoutMode === 'list' ? 'editor-layout-list overflow-x-auto' : 'editor-layout-composition overflow-x-hidden w-full'"
      @scroll.passive="hideEditorSelectionHint"
      @pointerdown.capture="onCanvasPointerDown"
      @click="onCanvasClick"
      @dblclick="onCanvasDblClick"
      @contextmenu="onCanvasContextMenu"
    >
      <UEditor
        ref="editorRef"
        :model-value="currentViewDoc"
        content-type="json"
        :on-create="onEditorCreate"
        :extensions="customExtensions"
        :starter-kit="{ heading: false, horizontalRule: false, blockquote: false, codeBlock: false }"
        :ui="{ base: 'px-3 py-2 min-h-full' }"
        class="min-h-full w-full"
        @update:model-value="onDocUpdate"
      />
    </div>

    <EditorSelectionHintBubble
      :visible="editorSelectionHint.visible"
      :message="editorSelectionHint.message"
      :x="editorSelectionHint.x"
      :y="editorSelectionHint.y"
    />

    <div
      v-if="listReorder.mode === 'dragging' && listReorder.draggingSegmentId"
      class="workspace-reorder-ghost"
      :style="dragGhostStyle"
    >
      <span
        v-if="dragGhostLineNumber !== null"
        class="workspace-reorder-ghost-line"
      >
        {{ String(dragGhostLineNumber).padStart(2, "0") }}
      </span>
      <span class="workspace-reorder-ghost-text">
        {{ dragGhostText || "拖动当前段" }}
      </span>
    </div>

    <EndSessionDialog
      v-model:visible="endSessionDialogVisible"
      :mode="endSessionDialogMode"
      :loading="isEndingSession"
      @choose="finalizeEndSession"
    />

    <SegmentContextMenu
      :visible="contextMenu.visible"
      :x="contextMenu.x"
      :y="contextMenu.y"
      :segment-id="contextMenu.segmentId"
      :can-delete="canDeleteFromMenu"
      @close="closeContextMenu"
      @delete="executeDeleteSegment"
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

:deep(.ProseMirror[contenteditable="false"]) {
  cursor: default;
  user-select: none;
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
  margin: 0 -2px;
  padding: 1px 2px;
  transition:
    background-color 0.15s ease,
    color 0.3s ease,
    box-shadow 0.15s ease;
}

:deep(.segment-dirty) {
  background: rgba(245, 158, 11, 0.14);
  box-shadow: inset 0 0 0 1px rgba(245, 158, 11, 0.32);
}

html.dark :deep(.segment-dirty) {
  background: rgba(245, 158, 11, 0.2);
  box-shadow: inset 0 0 0 1px rgba(251, 191, 36, 0.36);
}

:deep(.segment-playing) {
  color: var(--color-accent);
  font-weight: 700;
}

:deep(.segment-editing-playing) {
  background: color-mix(in srgb, var(--color-accent) 18%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 32%, transparent);
}

html.dark :deep(.segment-editing-playing) {
  background: color-mix(in srgb, var(--color-accent) 24%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 38%, transparent);
}

:deep(.segment-selected) {
  background: rgba(59, 130, 246, 0.12);
}

html.dark :deep(.segment-selected) {
  background: rgba(96, 165, 250, 0.18);
}

:deep(.ProseMirror .segment-block) {
  --segment-block-accent-width: 0px;
  --segment-block-accent-color: transparent;
  position: relative;
  display: flex;
  align-items: stretch;
  border-radius: 8px;
  transition:
    background-color 0.15s ease,
    color 0.3s ease,
    box-shadow 0.15s ease,
    border-color 0.15s ease;
}

:deep(.ProseMirror .segment-block)::before {
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: var(--segment-block-accent-width);
  background: var(--segment-block-accent-color);
  border-top-left-radius: inherit;
  border-bottom-left-radius: inherit;
  pointer-events: none;
}

.editor-layout-list :deep(.ProseMirror) {
  width: max-content;
  min-width: 100%;
}

.editor-layout-list :deep(.ProseMirror .segment-block) {
  white-space: nowrap;
}

:deep(.ProseMirror .segment-block-gutter) {
  flex: 0 0 38px;
  display: flex;
  align-items: center;
  justify-content: center;
}

:deep(.ProseMirror .segment-block-content) {
  min-width: 0;
  padding: 6px 10px 6px 0;
}

:deep(.ProseMirror .segment-block .segment-reorder-handle) {
  display: inline-flex;
  height: 24px;
  width: 24px;
  transform: translateZ(0);
  will-change: transform, opacity, background-color;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border-radius: 6px;
  color: var(--color-muted-fg);
  transition:
    background-color 0.15s ease,
    color 0.15s ease,
    opacity 0.15s ease,
    transform 0.15s ease;
}

:deep(.ProseMirror .segment-block .segment-reorder-line-number) {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.04em;
  opacity: 0.85;
  transition: opacity 0.15s ease;
}

:deep(.ProseMirror .segment-block .segment-reorder-grip) {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.15s ease;
}

:deep(.ProseMirror .segment-block .segment-reorder-handle:hover) {
  background: rgba(148, 163, 184, 0.12);
  color: var(--color-foreground);
}

html.dark :deep(.ProseMirror .segment-block .segment-reorder-handle:hover) {
  background: rgba(148, 163, 184, 0.18);
}

:deep(.ProseMirror .segment-block .segment-reorder-handle:hover .segment-reorder-line-number) {
  opacity: 0;
}

:deep(.ProseMirror .segment-block .segment-reorder-handle:hover .segment-reorder-grip) {
  opacity: 0.9;
}

:deep(.ProseMirror .segment-block .segment-reorder-handle[data-visible="false"]) {
  pointer-events: none;
}

:deep(.ProseMirror .segment-block .segment-reorder-handle[data-visible="false"] .segment-reorder-grip) {
  opacity: 0;
}

:deep(.ProseMirror .segment-block.segment-line-editing .segment-reorder-handle) {
  pointer-events: none;
}

:deep(.ProseMirror .segment-block.segment-line-editing .segment-reorder-line-number),
:deep(.ProseMirror .segment-block.segment-line-editing .segment-reorder-grip) {
  opacity: 0;
}

:deep(.ProseMirror .segment-block.segment-line-dirty) {
  --segment-block-accent-width: 3px;
  --segment-block-accent-color: var(--color-warning);
  background: rgba(245, 158, 11, 0.06);
}

html.dark :deep(.ProseMirror .segment-block.segment-line-dirty) {
  background: rgba(245, 158, 11, 0.10);
}

:deep(.ProseMirror .segment-block.segment-line-selected) {
  background: rgba(59, 130, 246, 0.12);
}

html.dark :deep(.ProseMirror .segment-block.segment-line-selected) {
  background: rgba(96, 165, 250, 0.18);
}

:deep(.ProseMirror .segment-block.segment-line-playing) {
  color: var(--color-accent);
  font-weight: 700;
}

:deep(.ProseMirror .segment-block.segment-line-reorder-source) {
  background: rgba(59, 130, 246, 0.08);
  box-shadow: inset 0 0 0 1px rgba(59, 130, 246, 0.22);
}

html.dark :deep(.ProseMirror .segment-block.segment-line-reorder-source) {
  background: rgba(96, 165, 250, 0.14);
  box-shadow: inset 0 0 0 1px rgba(96, 165, 250, 0.28);
}

:deep(.ProseMirror .segment-block.segment-line-reorder-source .segment-reorder-handle) {
  background: rgba(59, 130, 246, 0.14);
  color: rgb(37 99 235);
}

html.dark :deep(.ProseMirror .segment-block.segment-line-reorder-source .segment-reorder-handle) {
  background: rgba(96, 165, 250, 0.2);
  color: rgb(147 197 253);
}

:deep(.ProseMirror .segment-block.segment-line-drop-swap) {
  box-shadow: inset 0 0 0 1px rgba(14, 165, 233, 0.38);
  background: rgba(14, 165, 233, 0.08);
}

html.dark :deep(.ProseMirror .segment-block.segment-line-drop-swap) {
  box-shadow: inset 0 0 0 1px rgba(56, 189, 248, 0.42);
  background: rgba(56, 189, 248, 0.12);
}

:deep(.ProseMirror .segment-block.segment-line-drop-before) {
  box-shadow: inset 0 2px 0 0 rgba(14, 165, 233, 0.8);
  border-top-left-radius: 0;
  border-top-right-radius: 0;
}

:deep(.ProseMirror .segment-block.segment-line-drop-after) {
  box-shadow: inset 0 -2px 0 0 rgba(14, 165, 233, 0.8);
  border-bottom-left-radius: 0;
  border-bottom-right-radius: 0;
}

html.dark :deep(.ProseMirror .segment-block.segment-line-drop-before) {
  box-shadow: inset 0 2px 0 0 rgba(56, 189, 248, 0.86);
}

html.dark :deep(.ProseMirror .segment-block.segment-line-drop-after) {
  box-shadow: inset 0 -2px 0 0 rgba(56, 189, 248, 0.86);
}

:deep(.ProseMirror .segment-block.segment-line-submitting) {
  opacity: 0.72;
}

:deep(.ProseMirror .segment-block.segment-line-editing-playing) {
  background: color-mix(in srgb, var(--color-accent) 14%, transparent);
  --segment-block-accent-color: color-mix(in srgb, var(--color-accent) 58%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 20%, transparent);
}

html.dark :deep(.ProseMirror .segment-block.segment-line-editing-playing) {
  background: color-mix(in srgb, var(--color-accent) 20%, transparent);
  --segment-block-accent-color: color-mix(in srgb, var(--color-accent) 64%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 28%, transparent);
}

:deep(.ProseMirror .segment-block.segment-line-editing-playing [data-pause-boundary] button) {
  background: color-mix(in srgb, var(--color-accent) 12%, transparent);
  border-color: color-mix(in srgb, var(--color-accent) 35%, transparent);
  color: var(--color-accent);
}

:deep(.ProseMirror [data-pause-boundary]) {
  display: inline-block;
  vertical-align: baseline;
}

:deep(.ProseMirror [data-pause-boundary] button) {
  box-sizing: border-box;
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  height: 19.62px;
  padding-block: 0;
  font-size: 11px;
  line-height: normal;
  vertical-align: baseline;
  transition:
    background-color 0.15s ease,
    color 0.3s ease,
    border-color 0.15s ease,
    box-shadow 0.15s ease;
}

:deep(.ProseMirror .segment-block.segment-line-selected [data-pause-boundary] button) {
  background: rgba(59, 130, 246, 0.12);
  border-color: rgba(59, 130, 246, 0.28);
  color: rgb(37 99 235);
}

html.dark :deep(.ProseMirror .segment-block.segment-line-selected [data-pause-boundary] button) {
  background: rgba(96, 165, 250, 0.18);
  border-color: rgba(96, 165, 250, 0.3);
  color: rgb(147 197 253);
}

:deep(.ProseMirror .segment-block.segment-line-playing [data-pause-boundary] button) {
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

.workspace-reorder-ghost {
  position: fixed;
  z-index: 40;
  display: inline-flex;
  max-width: min(520px, calc(100vw - 32px));
  align-items: center;
  gap: 10px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 18px 40px rgba(15, 23, 42, 0.16);
  border-radius: 12px;
  padding: 10px 12px;
  pointer-events: none;
  transform: translate3d(0, 0, 0);
  backdrop-filter: blur(10px);
}

html.dark .workspace-reorder-ghost {
  border-color: rgba(148, 163, 184, 0.16);
  background: rgba(15, 23, 42, 0.92);
  box-shadow: 0 20px 44px rgba(2, 6, 23, 0.42);
}

.workspace-reorder-ghost-line {
  flex: 0 0 auto;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  color: var(--color-muted-fg);
}

.workspace-reorder-ghost-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-foreground);
}

:deep(.ProseMirror .is-editor-empty:first-child::before) {
  color: var(--color-muted-fg);
  opacity: 0.5;
}
</style>
