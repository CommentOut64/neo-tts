import { Extension } from "@tiptap/core";
import { Plugin } from "@tiptap/pm/state";

import { normalizeEditorPastedText } from "./documentModel";

export const SegmentEditingGuards = Extension.create({
  name: "segmentEditingGuards",

  addKeyboardShortcuts() {
    return {
      Enter: () => true,
      "Shift-Enter": () => true,
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
