import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

export const segmentDecorationKey = new PluginKey('segmentDecoration')

/** 外部状态，由 WorkspaceEditorHost 通过 storage 注入 */
export interface SegmentDecorationState {
  segmentIds: string[]
  playingId: string | null
  selectedIds: Set<string>
  dirtyIds: Set<string>
  isEditing: boolean
}

/**
 * 段级 Decoration 扩展
 *
 * 为每个顶层 paragraph 添加 Node Decoration，根据段的播放/选择/脏态
 * 赋予不同 CSS class 和 data-segment-id 属性。
 *
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
            const s = extensionStorage.state
            if (!s || s.segmentIds.length === 0) return DecorationSet.empty

            const decorations: Decoration[] = []
            let paragraphIndex = 0

            editorState.doc.forEach((node, offset) => {
              if (node.type.name !== 'paragraph') {
                return
              }

              const segId = s.segmentIds[paragraphIndex]
              paragraphIndex++

              if (!segId) return

              const classes: string[] = ['segment-paragraph']

              if (s.dirtyIds.has(segId)) {
                classes.push('segment-dirty')
              }

              // 展示态才渲染播放和选择高亮（编辑态弱化）
              if (!s.isEditing) {
                if (s.playingId === segId) {
                  classes.push('segment-playing')
                }
                if (s.selectedIds.has(segId)) {
                  classes.push('segment-selected')
                }
              }

              decorations.push(
                Decoration.node(offset, offset + node.nodeSize, {
                  class: classes.join(' '),
                  'data-segment-id': segId
                })
              )
            })

            return DecorationSet.create(editorState.doc, decorations)
          }
        }
      })
    ]
  }
})
