import type { EditorToolbarItem } from '@nuxt/ui'

/**
 * 编辑态最小工具条配置。
 * 仅保留撤销/重做，不暴露任何富文本格式化能力。
 */
export function buildEditorToolbar(): EditorToolbarItem[][] {
  return [[
    { kind: 'undo', icon: 'i-lucide-undo', tooltip: { text: '撤销' } },
    { kind: 'redo', icon: 'i-lucide-redo', tooltip: { text: '重做' } }
  ]]
}
