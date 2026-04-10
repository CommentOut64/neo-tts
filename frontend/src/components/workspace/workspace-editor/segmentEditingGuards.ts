import { Extension } from "@tiptap/core";
import { Plugin } from "@tiptap/pm/state";

import { normalizeEditorPastedText } from "./documentModel";

function selectionTouchesPauseBoundary(view: Parameters<NonNullable<InstanceType<typeof Plugin>["props"]>["handlePaste"]>[0]) {
  const { selection, doc } = view.state;
  if (selection.empty) {
    const before = selection.$from.nodeBefore;
    const after = selection.$from.nodeAfter;
    return before?.type.name === "pauseBoundary" || after?.type.name === "pauseBoundary";
  }

  let touchesBoundary = false;
  doc.nodesBetween(
    Math.max(0, selection.from - 1),
    Math.min(doc.content.size, selection.to + 1),
    (node) => {
      if (node.type.name === "pauseBoundary") {
        touchesBoundary = true;
        return false;
      }
      return undefined;
    },
  );
  return touchesBoundary;
}

export const SegmentEditingGuards = Extension.create({
  name: "segmentEditingGuards",

  addKeyboardShortcuts() {
    return {
      Enter: () => true,
      "Shift-Enter": () => true,
      Backspace: ({ editor }) => selectionTouchesPauseBoundary(editor.view),
      Delete: ({ editor }) => selectionTouchesPauseBoundary(editor.view),
    };
  },

  addProseMirrorPlugins() {
    return [
      new Plugin({
        props: {
          handlePaste(view, event) {
            const plainText = event.clipboardData?.getData("text/plain");
            if (!plainText || (!plainText.includes("\n") && !plainText.includes("\r"))) {
              return false;
            }

            event.preventDefault();
            const normalizedText = normalizeEditorPastedText(plainText);
            if (normalizedText.length > 0) {
              view.dispatch(view.state.tr.insertText(normalizedText));
            }
            return true;
          },
        },
      }),
    ];
  },
});
