import { Extension } from '@tiptap/core'
import type { JSONContent } from '@tiptap/vue-3'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import type { EditorState } from '@tiptap/pm/state'
import type { PlaybackCursor } from '@/types/editSession'

import type { WorkspaceEditorLayoutMode, WorkspaceRenderMap } from './layoutTypes'
import type { ListDropIntent } from './listReorderTypes'
import { extractRenderMapFromDoc } from './extractRenderMapFromDoc'

export const segmentDecorationKey = new PluginKey('segmentDecoration')

/** 外部状态，由 WorkspaceEditorHost 通过 storage 注入 */
export interface SegmentDecorationState {
  layoutMode: WorkspaceEditorLayoutMode
  renderMap: WorkspaceRenderMap | null
  showReorderHandle: boolean
  playingId: string | null
  playingCursor?: PlaybackCursor | null
  selectedIds: Set<string>
  dirtyIds: Set<string>
  dirtyEdgeIds: Set<string>
  isEditing: boolean
  draggingSegmentId?: string | null
  dropTargetSegmentId?: string | null
  dropIntent?: ListDropIntent | null
  isSubmittingReorder?: boolean
}

export interface SegmentDecorationSpec {
  kind: "inline" | "node"
  from: number
  to: number
  attrs: Record<string, string>
}

function resolvePlayingSegmentId(state: SegmentDecorationState) {
  if (state.playingCursor) {
    return state.playingCursor.kind === "segment"
      ? state.playingCursor.segmentId
      : null
  }

  return state.playingId
}

function resolveSegmentFragmentRole(
  ranges: WorkspaceRenderMap["segmentRanges"],
  index: number,
) {
  const current = ranges[index]
  const previous = ranges[index - 1]
  const next = ranges[index + 1]
  const joinsPrevious =
    previous?.segmentId === current.segmentId && previous.to === current.from
  const joinsNext =
    next?.segmentId === current.segmentId && current.to === next.from

  if (!joinsPrevious && !joinsNext) {
    return "single"
  }
  if (!joinsPrevious) {
    return "start"
  }
  if (!joinsNext) {
    return "end"
  }
  return "middle"
}

function buildCompositionSegmentDecorationSpecs(
  state: SegmentDecorationState,
  ranges: WorkspaceRenderMap["segmentRanges"],
): SegmentDecorationSpec[] {
  const playingSegmentId = resolvePlayingSegmentId(state)

  if (ranges.length === 0) {
    return []
  }

  return ranges.map((range, index) => {
    const fragmentRole = resolveSegmentFragmentRole(ranges, index)
    const classes: string[] = [
      "segment-fragment",
      `segment-fragment-${fragmentRole}`,
    ]

    const shouldHighlightDirty =
      state.dirtyIds.has(range.segmentId) &&
      !state.isEditing

    if (shouldHighlightDirty) {
      classes.push("segment-dirty")
    }

    if (playingSegmentId === range.segmentId) {
      classes.push(
        state.isEditing
          ? "segment-editing-playing"
          : "segment-playing",
      )
    }

    if (!state.isEditing) {
      if (state.selectedIds.has(range.segmentId)) {
        classes.push("segment-selected")
      }
    }

    return {
      kind: "inline",
      from: range.from,
      to: range.to,
      attrs: {
        class: classes.join(' '),
        'data-segment-id': range.segmentId,
      },
    }
  })
}

export function buildSegmentDecorationSpecs(
  state: SegmentDecorationState | null,
): SegmentDecorationSpec[] {
  if (!state?.renderMap) {
    return []
  }

  if (state.layoutMode === "list") {
    return []
  }

  const ranges = state.renderMap.segmentRanges
  return buildCompositionSegmentDecorationSpecs(state, ranges)
}

export function buildLiveSegmentDecorationSpecsFromDoc(
  doc: JSONContent,
  state: SegmentDecorationState | null,
): SegmentDecorationSpec[] {
  if (!state?.renderMap || state.layoutMode === "list") {
    return []
  }

  const liveRenderMap = extractRenderMapFromDoc(
    doc,
    state.renderMap.orderedSegmentIds,
    state.layoutMode,
  )
  return buildCompositionSegmentDecorationSpecs(
    state,
    liveRenderMap.segmentRanges,
  )
}

function buildListSegmentDecorationAttrs(
  state: SegmentDecorationState,
  segmentId: string,
) {
  const classes = ["segment-line"]
  const playingSegmentId = resolvePlayingSegmentId(state)

  if (state.dirtyIds.has(segmentId)) {
    classes.push("segment-line-dirty")
  }

  if (playingSegmentId === segmentId) {
    classes.push(
      state.isEditing
        ? "segment-line-editing-playing"
        : "segment-line-playing",
    )
  }

  if (state.isEditing) {
    classes.push("segment-line-editing")
  }

  if (!state.isEditing && state.selectedIds.has(segmentId)) {
    classes.push("segment-line-selected")
  }

  if (state.draggingSegmentId === segmentId) {
    classes.push("segment-line-reorder-source")
  }

  if (state.dropTargetSegmentId === segmentId) {
    if (state.dropIntent === "swap") {
      classes.push("segment-line-drop-swap")
    } else if (state.dropIntent === "insert-before") {
      classes.push("segment-line-drop-before")
    } else if (state.dropIntent === "insert-after") {
      classes.push("segment-line-drop-after")
    }
  }

  if (state.isSubmittingReorder) {
    classes.push("segment-line-submitting")
  }

  return {
    class: classes.join(" "),
    "data-segment-id": segmentId,
  }
}

function buildListSegmentDecorations(
  editorState: EditorState,
  state: SegmentDecorationState | null,
) {
  if (!state || state.layoutMode !== "list") {
    return [] as Decoration[]
  }

  const decorations: Decoration[] = []
  editorState.doc.descendants((node, pos) => {
    if (node.type.name !== "segmentBlock") {
      return
    }

    const segmentId =
      typeof node.attrs.segmentId === "string" ? node.attrs.segmentId : null
    if (!segmentId) {
      return
    }

    decorations.push(
      Decoration.node(
        pos,
        pos + node.nodeSize,
        buildListSegmentDecorationAttrs(state, segmentId),
      ),
    )
  })
  return decorations
}

/**
 * 段级 Decoration 扩展
 *
 * 组合式使用 inline decoration，仅高亮文本片段；
 * 列表式使用 node decoration，高亮整行 paragraph，并把状态透传给停顿节点。
 * 外部通过更新 editor.storage.segmentDecoration.state 并 dispatch
 * 一个带 segmentDecorationKey meta 的空 transaction 来触发重建。
 */
export const SegmentDecoration = Extension.create<Record<string, never>, { state: SegmentDecorationState | null }>({
  name: 'segmentDecoration',

  addStorage() {
    return {
      state: null as SegmentDecorationState | null
    }
  },

  addProseMirrorPlugins() {
    const extensionStorage = this.storage

    return [
      new Plugin({
        key: segmentDecorationKey,

        props: {
          decorations(editorState) {
            const decorations =
              extensionStorage.state?.layoutMode === "list"
                ? buildListSegmentDecorations(editorState, extensionStorage.state)
                : buildLiveSegmentDecorationSpecsFromDoc(
                    editorState.doc.toJSON() as JSONContent,
                    extensionStorage.state,
                  ).map((spec) =>
                    spec.kind === "node"
                      ? Decoration.node(spec.from, spec.to, spec.attrs)
                      : Decoration.inline(spec.from, spec.to, spec.attrs),
                  )

            return decorations.length > 0
              ? DecorationSet.create(editorState.doc, decorations)
              : DecorationSet.empty
          }
        }
      })
    ]
  }
})
