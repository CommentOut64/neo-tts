import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

import type { WorkspaceEditorLayoutMode, WorkspaceRenderMap } from './layoutTypes'

export const segmentDecorationKey = new PluginKey('segmentDecoration')

/** 外部状态，由 WorkspaceEditorHost 通过 storage 注入 */
export interface SegmentDecorationState {
  layoutMode: WorkspaceEditorLayoutMode
  renderMap: WorkspaceRenderMap | null
  playingId: string | null
  selectedIds: Set<string>
  dirtyIds: Set<string>
  dirtyEdgeIds: Set<string>
  isEditing: boolean
}

export interface SegmentDecorationSpec {
  kind: "inline" | "node"
  from: number
  to: number
  attrs: Record<string, string>
}

export function buildSegmentDecorationSpecs(
  state: SegmentDecorationState | null,
): SegmentDecorationSpec[] {
  if (!state?.renderMap) {
    return []
  }

  const ranges =
    state.layoutMode === "list"
      ? state.renderMap.segmentBlockRanges
      : state.renderMap.segmentRanges

  if (ranges.length === 0) {
    return []
  }

  return ranges.map((range) => {
    const classes: string[] =
      state.layoutMode === "list" ? ["segment-line"] : ["segment-fragment"]

    const shouldHighlightDirty =
      state.dirtyIds.has(range.segmentId) &&
      (state.layoutMode === "list" || !state.isEditing)

    if (shouldHighlightDirty) {
      classes.push(
        state.layoutMode === "list" ? "segment-line-dirty" : "segment-dirty",
      )
    }

    if (state.playingId === range.segmentId) {
      classes.push(
        state.layoutMode === "list"
          ? state.isEditing
            ? "segment-line-editing-playing"
            : "segment-line-playing"
          : state.isEditing
            ? "segment-editing-playing"
            : "segment-playing",
      )
    }

    if (!state.isEditing) {
      if (state.selectedIds.has(range.segmentId)) {
        classes.push(
          state.layoutMode === "list" ? "segment-line-selected" : "segment-selected",
        )
      }
    }

    return {
      kind: state.layoutMode === "list" ? "node" : "inline",
      from: range.from,
      to: range.to,
      attrs: {
        class: classes.join(' '),
        'data-segment-id': range.segmentId,
      },
    }
  })
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
            const decorations = buildSegmentDecorationSpecs(extensionStorage.state).map((spec) =>
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
