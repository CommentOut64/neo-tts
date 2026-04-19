import { Extension } from "@tiptap/core";
import { NodeSelection, Plugin } from "@tiptap/pm/state";

import { normalizeEditorPastedText } from "./documentModel";

type EditorViewLike = Parameters<NonNullable<InstanceType<typeof Plugin>["props"]>["handlePaste"]>[0];

export interface SegmentEditingGuardOptions {
  onProtectedTerminalCapsule: () => void;
}

function selectionIncludesPauseBoundary(view: EditorViewLike) {
  const { selection, doc } = view.state;
  if (selection instanceof NodeSelection) {
    return selection.node.type.name === "pauseBoundary";
  }

  if (selection.empty) {
    return false;
  }

  let touchesBoundary = false;
  doc.nodesBetween(
    selection.from,
    selection.to,
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

function backspaceTouchesPauseBoundary(view: EditorViewLike) {
  const { selection } = view.state;
  if (selection.empty) {
    return selection.$from.nodeBefore?.type.name === "pauseBoundary";
  }
  return selectionIncludesPauseBoundary(view);
}

function deleteTouchesPauseBoundary(view: EditorViewLike) {
  const { selection } = view.state;
  if (selection.empty) {
    return selection.$from.nodeAfter?.type.name === "pauseBoundary";
  }
  return selectionIncludesPauseBoundary(view);
}

export const SegmentEditingGuards = Extension.create<SegmentEditingGuardOptions>({
  name: "segmentEditingGuards",

  addOptions() {
    return {
      onProtectedTerminalCapsule: () => {},
    };
  },

  addKeyboardShortcuts() {
    return {
      Enter: () => true,
      "Shift-Enter": () => true,
      Backspace: ({ editor }) => backspaceTouchesPauseBoundary(editor.view),
      Delete: ({ editor }) => deleteTouchesPauseBoundary(editor.view),
    };
  },

  addProseMirrorPlugins() {
    return [
      new Plugin({
        props: {
          handleDrop() {
            return false;
          },
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
