import type { Editor } from "@tiptap/vue-3";

export function buildEditorToolbar(editor: Editor) {
  return [
    [
      {
        label: "加粗",
        icon: "i-lucide-bold",
        action: () => editor.chain().focus().toggleBold().run(),
        active: editor.isActive("bold"),
      },
      {
        label: "斜体",
        icon: "i-lucide-italic",
        action: () => editor.chain().focus().toggleItalic().run(),
        active: editor.isActive("italic"),
      },
      {
        label: "下划线",
        icon: "i-lucide-underline",
        action: () => editor.chain().focus().toggleUnderline().run(),
        active: editor.isActive("underline"),
      },
    ],
    [
      {
        label: "撤销",
        icon: "i-lucide-undo",
        action: () => editor.chain().focus().undo().run(),
        disabled: !editor.can().undo(),
      },
      {
        label: "重做",
        icon: "i-lucide-redo",
        action: () => editor.chain().focus().redo().run(),
        disabled: !editor.can().redo(),
      },
    ],
  ];
}
