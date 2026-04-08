<script setup lang="ts">
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'
import { ElMessage } from "element-plus";
import type { JSONContent } from '@tiptap/vue-3'
import { useEditSession } from '@/composables/useEditSession'
import { useInputDraft } from '@/composables/useInputDraft'
import { useWorkspaceLightEdit } from '@/composables/useWorkspaceLightEdit'
import { useWorkspaceDraftPersistence } from '@/composables/useWorkspaceDraftPersistence'
import { usePlayback } from '@/composables/usePlayback'
import { useSegmentSelection } from '@/composables/useSegmentSelection'
import { useRuntimeState } from '@/composables/useRuntimeState'
import { extractWorkspaceEffectiveText } from '@/utils/workspaceEffectiveText'
import type { WorkspaceDraftMode } from '@/utils/workspaceDraftSnapshot'
import { buildEditorExtensions } from './workspace-editor/buildEditorExtensions'
import { segmentDecorationKey } from './workspace-editor/segmentDecoration'
import ResetSessionDialog from './ResetSessionDialog.vue'
import { buildSessionHeadText } from './sessionHandoff'
import {
  buildSegmentEditorDocument,
  collectSegmentDraftChanges,
} from "./workspace-editor/documentModel";

const emit = defineEmits<{
  (e: 'backfill-to-text-input'): void
}>()

const WORKSPACE_DRAFT_SAVE_DEBOUNCE_MS = 200

// --- composable 实例 ---
const editSession = useEditSession()
const inputDraft = useInputDraft()
const lightEdit = useWorkspaceLightEdit()
const workspaceDraftPersistence = useWorkspaceDraftPersistence()
const { currentSegmentId, seekToSegment, play } = usePlayback()
const segmentSelection = useSegmentSelection()
const runtimeState = useRuntimeState()

const resetSessionDialogVisible = ref(false)

// --- 内部状态 ---
const isEditing = ref(false)
const segmentIds = ref<string[]>([])
const docJson = ref<JSONContent>({ type: 'doc', content: [] })
const restoredSessionKey = ref<string | null>(null)

// UEditor ref（通过 expose 拿到 editor 实例）
const editorRef = ref<{ editor: any } | null>(null)
let draftPersistTimeoutId: number | null = null

// 编辑态扩展
const customExtensions = buildEditorExtensions()

const sortedReadySegments = computed(() =>
  [...editSession.segments.value].sort((left, right) => left.order_key - right.order_key),
)

const currentDocumentId = computed(() =>
  sortedReadySegments.value[0]?.document_id ?? editSession.snapshot.value?.document_id ?? null,
)

const currentDocumentVersion = computed(() => editSession.documentVersion.value)
const currentSessionHeadText = computed(() => buildSessionHeadText(sortedReadySegments.value))
const currentSessionSegmentIds = computed(() =>
  sortedReadySegments.value.map((segment) => segment.segment_id),
)

const currentSessionKey = computed(() => {
  if (
    editSession.sessionStatus.value !== 'ready' ||
    runtimeState.isInitialRendering.value ||
    !editSession.segmentsLoaded.value ||
    !currentDocumentId.value ||
    currentDocumentVersion.value === null
  ) {
    return null
  }

  return [
    currentDocumentId.value,
    String(currentDocumentVersion.value),
    currentSessionSegmentIds.value.join('|'),
  ].join('::')
})

// --- 字数统计 ---
const charCount = computed(() => {
  const editor = editorRef.value?.editor
  if (!editor) return 0
  return editor.state.doc.textContent.length
})

// --- 模式标签 ---
const modeLabel = computed(() => isEditing.value ? '编辑' : '展示')

function clearPendingDraftPersist() {
  if (draftPersistTimeoutId === null) {
    return
  }

  window.clearTimeout(draftPersistTimeoutId)
  draftPersistTimeoutId = null
}

onBeforeUnmount(() => {
  clearPendingDraftPersist()
})

function buildSegmentDraftRecord(
  drafts: Map<string, string> = lightEdit.draftTextBySegmentId.value,
): Record<string, string> {
  return Object.fromEntries(drafts)
}

function syncInputBackToSessionIfNeeded() {
  if (inputDraft.source.value !== 'workspace') {
    return
  }

  editSession.syncInputDraftToSessionText(currentSessionHeadText.value)
}

function syncInputFromWorkspaceEffectiveText(effectiveText: string) {
  if (
    effectiveText !== currentSessionHeadText.value ||
    inputDraft.source.value === 'workspace'
  ) {
    inputDraft.syncFromWorkspaceDraft(effectiveText)
  }
}

function persistWorkspaceDraftSnapshot(
  mode: WorkspaceDraftMode,
  editorDoc: JSONContent,
  segmentDrafts: Record<string, string> = buildSegmentDraftRecord(),
) {
  if (!currentDocumentId.value || currentDocumentVersion.value === null) {
    return
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
  })
}

function clearPersistedWorkspaceDraft() {
  if (!currentDocumentId.value) {
    return
  }

  workspaceDraftPersistence.clearSnapshot(currentDocumentId.value)
}

function syncPreviewWorkspaceState(editorDoc: JSONContent) {
  if (lightEdit.dirtyCount.value === 0) {
    clearPersistedWorkspaceDraft()
    syncInputBackToSessionIfNeeded()
    return
  }

  const effectiveText = extractWorkspaceEffectiveText(editorDoc)
  persistWorkspaceDraftSnapshot('preview', editorDoc)
  syncInputFromWorkspaceEffectiveText(effectiveText)
}

// --- 文档构建：ready 态 ---
function rebuildDocFromSegments() {
  if (isEditing.value) return // 编辑中不重建

  const segs = editSession.segments.value
  if (!editSession.segmentsLoaded.value || segs.length === 0) {
    segmentIds.value = []
    docJson.value = { type: 'doc', content: [{ type: 'paragraph', content: [] }] }
    pushContentToEditor()
    return
  }

  const sorted = [...segs].sort((a, b) => a.order_key - b.order_key)
  segmentIds.value = sorted.map(s => s.segment_id)

  docJson.value = {
    ...buildSegmentEditorDocument(
      sorted.map((segment) => ({
        segmentId: segment.segment_id,
        text: lightEdit.getDraft(segment.segment_id) ?? segment.raw_text,
      })),
    ),
  }
  pushContentToEditor()
  syncPreviewWorkspaceState(docJson.value)
}

// --- 文档构建：initializing 态（渐进显示） ---
function rebuildDocFromProgressiveSegments() {
  if (isEditing.value) return

  const progressive = runtimeState.progressiveSegments.value
  if (progressive.length === 0) {
    segmentIds.value = []
    docJson.value = { type: 'doc', content: [{ type: 'paragraph', content: [] }] }
    pushContentToEditor()
    return
  }

  segmentIds.value = progressive.map(s => s.segmentId)

  docJson.value = buildSegmentEditorDocument(
    progressive.map((segment) => ({
      segmentId: segment.segmentId,
      text: segment.renderStatus === "completed" ? segment.rawText : "",
    })),
  )
  pushContentToEditor()
}

/** 将 docJson 推送到 TipTap 编辑器（model-value 不会驱动已挂载编辑器重渲染） */
function pushContentToEditor(editorOverride?: any) {
  nextTick(() => {
    const editor = editorOverride ?? editorRef.value?.editor
    if (editor) {
      editor.commands.setContent(docJson.value)
      syncDecorationState(editor)
    }
  })
}

// --- 数据源 watcher ---
watch(
  currentSessionKey,
  () => {
    if (!currentSessionKey.value) {
      restoredSessionKey.value = null
      return
    }

    const snapshot = workspaceDraftPersistence.readCompatibleSnapshot({
      documentId: currentDocumentId.value!,
      documentVersion: currentDocumentVersion.value!,
      segmentIds: currentSessionSegmentIds.value,
    })

    clearPendingDraftPersist()

    if (snapshot) {
      isEditing.value = snapshot.mode === 'editing'
      lightEdit.replaceAllDrafts(snapshot.segmentDrafts)
      segmentIds.value = [...currentSessionSegmentIds.value]
      docJson.value = snapshot.editorDoc
      pushContentToEditor()
      syncInputFromWorkspaceEffectiveText(snapshot.effectiveText)
    } else {
      isEditing.value = false
      rebuildDocFromSegments()
    }

    restoredSessionKey.value = currentSessionKey.value
  },
  { immediate: true }
)

// ready 态：segments 或 lightEdit 变化时重建
watch(
  [() => editSession.segments.value, () => editSession.segmentsLoaded.value, () => lightEdit.dirtySegmentIds.value],
  () => {
    if (
      editSession.sessionStatus.value === 'ready' &&
      !runtimeState.isInitialRendering.value &&
      restoredSessionKey.value === currentSessionKey.value
    ) {
      rebuildDocFromSegments()
    }
  },
  { deep: true, immediate: true }
)

// initializing 态：progressiveSegments 变化时重建
watch(
  () => runtimeState.progressiveSegments.value,
  () => {
    if (runtimeState.isInitialRendering.value) {
      rebuildDocFromProgressiveSegments()
    }
  },
  { deep: true, immediate: true }
)

// --- Decoration 状态桥接 ---
function syncDecorationState(editorOverride?: any) {
  const editor = editorOverride ?? editorRef.value?.editor
  if (!editor) return

  editor.storage.segmentDecoration.state = {
    segmentIds: segmentIds.value,
    playingId: currentSegmentId.value,
    selectedIds: segmentSelection.selectedSegmentIds.value,
    dirtyIds: lightEdit.dirtySegmentIds.value,
    isEditing: isEditing.value
  }

  // dispatch 空 tr 触发 decoration 重建
  editor.view.dispatch(editor.state.tr.setMeta(segmentDecorationKey, true))
}

watch(
  [currentSegmentId, () => segmentSelection.selectedSegmentIds.value, () => lightEdit.dirtySegmentIds.value, isEditing, segmentIds],
  () => nextTick(syncDecorationState),
  { deep: true }
)

// editor 创建后：立刻同步当前文档，避免首次渐进内容在 editor 实例可用前丢失。
function onEditorCreate({ editor }: { editor: any }) {
  editor.setEditable(isEditing.value)
  pushContentToEditor(editor)
}

watch(
  () => editorRef.value?.editor,
  (editor) => {
    if (!editor) return
    editor.setEditable(isEditing.value)
    pushContentToEditor(editor)
  },
  { immediate: true }
)

watch(
  isEditing,
  (editing) => {
    const editor = editorRef.value?.editor
    if (!editor) return
    editor.setEditable(editing)
    nextTick(() => syncDecorationState(editor))
  }
)

watch(
  docJson,
  () => {
    if (!isEditing.value) {
      pushContentToEditor()
    }
  },
  { deep: true }
)

// --- 展示态交互 ---

function findSegmentIdFromEvent(event: MouseEvent): string | null {
  const target = (event.target as HTMLElement).closest('[data-segment-id]')
  if (!target) return null
  return target.getAttribute('data-segment-id')
}

function onCanvasClick(event: MouseEvent) {
  if (isEditing.value) return

  const segId = findSegmentIdFromEvent(event)
  if (!segId) {
    segmentSelection.clearSelection()
    return
  }

  const allIds = segmentIds.value

  if (event.shiftKey) {
    segmentSelection.rangeSelect(segId, allIds)
  } else if (event.ctrlKey || event.metaKey) {
    segmentSelection.toggleSelect(segId)
  } else {
    segmentSelection.select(segId)
  }

  seekToSegment(segId)
  play()
}

function onCanvasDblClick(event: MouseEvent) {
  if (isEditing.value) return
  
  const segId = findSegmentIdFromEvent(event)
  if (segId) {
    // 阻止浏览器默认的双击选词行为
    window.getSelection()?.removeAllRanges()
    enterEditMode(event)
  }
}

// --- 编辑态管理 ---

/** 获取后端事实态的段原始文本 */
function getBackendSegmentText(segId: string): string {
  const seg = editSession.segments.value.find(s => s.segment_id === segId)
  return seg?.raw_text ?? ''
}

function enterEditMode(clickEvent?: MouseEvent) {
  if (isEditing.value) return

  segmentSelection.clearSelection()
  isEditing.value = true

  nextTick(() => {
    const editor = editorRef.value?.editor
    if (editor) {
      if (clickEvent) {
        // 利用 TipTap/ProseMirror 的 posAtCoords 将点击坐标转换为光标位置
        const coords = { left: clickEvent.clientX, top: clickEvent.clientY }
        const pos = editor.view.posAtCoords(coords)
        if (pos) {
          editor.commands.focus()
          // 插入光标到点击位置，而不是选中文本
          editor.commands.setTextSelection(pos.pos)
        } else {
          editor.commands.focus()
        }
      } else {
        editor.commands.focus()
      }
    }
    syncDecorationState(editor)
  })
}

function commitAndExitEdit() {
  const editor = editorRef.value?.editor
  if (!editor) {
    clearPendingDraftPersist()
    isEditing.value = false
    return
  }

  try {
    const editorDoc = editor.getJSON()
    const changes = collectSegmentDraftChanges(
      editorDoc,
      segmentIds.value,
      getBackendSegmentText,
    )

    const nextDrafts = new Map(lightEdit.draftTextBySegmentId.value)
    changes.changedDrafts.forEach(([segmentId, text]) => {
      nextDrafts.set(segmentId, text)
    })
    changes.clearedSegmentIds.forEach((segmentId) => {
      nextDrafts.delete(segmentId)
    })

    clearPendingDraftPersist()
    docJson.value = editorDoc
    lightEdit.replaceAllDrafts(nextDrafts)
    if (nextDrafts.size > 0) {
      persistWorkspaceDraftSnapshot(
        'preview',
        editorDoc,
        buildSegmentDraftRecord(nextDrafts),
      )
      syncInputFromWorkspaceEffectiveText(extractWorkspaceEffectiveText(editorDoc))
    } else {
      clearPersistedWorkspaceDraft()
      syncInputBackToSessionIfNeeded()
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : "正文结构异常，无法提交编辑"
    ElMessage.error(message)
    return
  }

  isEditing.value = false
  // 不需要 rebuildDocFromSegments，因为 watch dirtySegmentIds 会触发重建
}

function discardAndExitEdit() {
  clearPendingDraftPersist()
  isEditing.value = false
  rebuildDocFromSegments()
}

function handleResetSessionSuccess() {
  segmentSelection.clearSelection()
  lightEdit.clearAll()
  clearPendingDraftPersist()
  isEditing.value = false
}

function onKeyDown(event: KeyboardEvent) {
  if (event.key === 'Escape' && isEditing.value) {
    event.preventDefault()
    event.stopPropagation()
    commitAndExitEdit()
  }
}

// --- UEditor model 更新回调（编辑态下不重建，避免循环） ---
function onDocUpdate(value: JSONContent) {
  if (!isEditing.value) {
    return
  }

  docJson.value = value
  clearPendingDraftPersist()
  draftPersistTimeoutId = window.setTimeout(() => {
    draftPersistTimeoutId = null
    persistWorkspaceDraftSnapshot('editing', value)
    syncInputFromWorkspaceEffectiveText(extractWorkspaceEffectiveText(value))
  }, WORKSPACE_DRAFT_SAVE_DEBOUNCE_MS)
}
</script>

<template>
  <section
    class="animate-fall flex-1 min-h-0 w-full bg-card rounded-card shadow-card border border-border dark:border-transparent overflow-hidden flex flex-col"
    @keydown="onKeyDown"
  >
    <!-- 头部区：固定最小高度以防止切换状态时由于按钮尺寸不同导致行高跳动 -->
    <header class="px-4 h-12 border-b border-border/70 dark:border-border/30 flex items-center justify-between shrink-0">
      <div class="flex items-center gap-2">
        <h3 class="text-sm font-semibold text-foreground leading-none">会话正文</h3>
        <span
          class="text-[10px] font-medium px-1.5 py-0.5 rounded leading-none"
          :class="isEditing
            ? 'bg-blue-500/10 text-blue-600 border border-blue-500/20'
            : 'bg-muted text-muted-fg border border-border/50'"
        >
          {{ modeLabel }}
        </span>
      </div>

      <div class="flex items-center justify-end min-w-[200px] gap-2">
        <!-- 字数统计 -->
        <span class="text-xs text-muted-fg mr-1">{{ charCount }} 字</span>

        <!-- 展示态：返回文本输入 / 编辑 / 清空会话 -->
        <button
          v-if="!isEditing"
          :disabled="segmentIds.length === 0"
          class="px-2.5 py-1 text-xs font-medium rounded border border-border text-foreground hover:bg-secondary/50 transition-colors disabled:cursor-not-allowed disabled:opacity-50"
          @click="emit('backfill-to-text-input')"
        >
          转到文本输入页继续编辑
        </button>
        <button
          v-if="!isEditing && segmentIds.length > 0"
          class="px-2.5 py-1 text-xs font-medium rounded border border-border text-foreground hover:bg-secondary/50 transition-colors"
          @click="enterEditMode"
        >
          编辑正文
        </button>
        <button
          v-if="!isEditing"
          class="px-2.5 py-1 text-xs font-medium rounded border border-destructive/30 text-destructive hover:bg-destructive/10 transition-colors"
          @click="resetSessionDialogVisible = true"
        >
          清空会话
        </button>

        <!-- 编辑态：完成 / 放弃 -->
        <template v-if="isEditing">
          <button
            class="px-2.5 py-1 text-xs font-medium rounded text-muted-fg hover:bg-secondary/50 transition-colors"
            @click="discardAndExitEdit"
          >
            放弃
          </button>
          <button
            class="hover-state-layer px-2.5 py-1 text-xs font-medium rounded bg-blue-500 text-white transition-colors shadow-sm"
            @click="commitAndExitEdit"
          >
            完成编辑
          </button>
        </template>
      </div>
    </header>

    <!-- 中部画布区 -->
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
        class="w-full min-h-full"
        @update:model-value="onDocUpdate"
      >
        <!-- 编辑态最小工具条（暂不启用） -->
      </UEditor>
    </div>

    <ResetSessionDialog
      v-model:visible="resetSessionDialogVisible"
      @success="handleResetSessionSuccess"
    />
  </section>
</template>

<style scoped>
/* === 连续正文画布基础 === */
:deep(.ProseMirror) {
  outline: none;
  font-family: inherit;
  font-size: 0.9375rem;
  line-height: 1.75;
  color: var(--color-foreground);
  min-height: 100%;
}

/* 编辑态文本选区 */
:deep(.ProseMirror ::selection) {
  background: rgba(59, 130, 246, 0.25);
}
html.dark :deep(.ProseMirror ::selection) {
  background: rgba(96, 165, 250, 0.35);
}

/* === 段落块 === */
:deep(.ProseMirror .segment-paragraph) {
  padding: 6px 10px;
  border-radius: 4px;
  border-left: 3px solid transparent;
  transition: background-color 0.15s ease, border-color 0.15s ease, color 0.3s ease, font-size 0.3s ease, font-weight 0.3s ease;
  cursor: default;
}

/* 展示态 hover */
:deep(.ProseMirror:not(.ProseMirror-focused) .segment-paragraph:hover) {
  background: rgba(0, 0, 0, 0.03);
}
html.dark :deep(.ProseMirror:not(.ProseMirror-focused) .segment-paragraph:hover) {
  background: rgba(255, 255, 255, 0.05);
}

/* === 脏段 — 橙色左边框 + 弱底色 === */
:deep(.segment-dirty) {
  border-left-color: var(--color-warning) !important;
  background: rgba(245, 158, 11, 0.06);
}
html.dark :deep(.segment-dirty) {
  background: rgba(245, 158, 11, 0.10);
}

/* === 播放高亮 — 采用文字高亮，引导阅读视线 === */
:deep(.segment-playing) {
  color: var(--color-accent) !important;
  font-weight: 700;
  font-size: 1.05em;
}

/* === 选择高亮 — 采用背景高亮，暗示操作域 === */
:deep(.segment-selected) {
  background: rgba(59, 130, 246, 0.12) !important;
}
html.dark :deep(.segment-selected) {
  background: rgba(96, 165, 250, 0.18) !important;
}

/* === 编辑态光标区域 === */
:deep(.ProseMirror-focused .segment-paragraph) {
  cursor: text;
}

/* === 移除 UEditor 默认大留白 === */
:deep(.ProseMirror > *) {
  margin-top: 0;
  margin-bottom: 0;
}
:deep(.ProseMirror p) {
  margin-top: 0;
  margin-bottom: 0;
}

/* === placeholder === */
:deep(.ProseMirror .is-editor-empty:first-child::before) {
  color: var(--color-muted-fg);
  opacity: 0.5;
}
</style>
