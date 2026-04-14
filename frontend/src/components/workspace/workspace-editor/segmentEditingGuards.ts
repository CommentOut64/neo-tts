import { Extension } from "@tiptap/core";
import { NodeSelection, Plugin } from "@tiptap/pm/state";

import { splitSegmentTerminalCapsule } from "@/utils/segmentTextDisplay";
import { normalizeEditorPastedText } from "./documentModel";

type EditorViewLike = Parameters<NonNullable<InstanceType<typeof Plugin>["props"]>["handlePaste"]>[0];

export interface SegmentEditingGuardOptions {
  onProtectedTerminalCapsule: () => void;
}

function isSegmentTextNode(node: { type: { name: string }; marks?: Array<{ type: { name: string } }>; text?: string }, parent: { type: { name: string } } | null) {
  if (node.type.name !== "text" || typeof node.text !== "string") {
    return false;
  }

  return (
    (node.marks ?? []).some((mark) => mark.type.name === "segmentAnchor") ||
    parent?.type.name === "segmentBlock"
  );
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

export function selectionIncludesTerminalCapsule(view: EditorViewLike) {
  const { selection, doc } = view.state;
  if (selection.empty) {
    return false;
  }

  let touchesCapsule = false;
  doc.nodesBetween(selection.from, selection.to, (node, pos, parent) => {
    if (!isSegmentTextNode(node, parent)) {
      return undefined;
    }

    const text = node.text ?? "";
    const capsule = splitSegmentTerminalCapsule(text).capsule;
    if (capsule.length === 0) {
      return undefined;
    }

    const nodeFrom = pos;
    const nodeTo = pos + text.length;
    const capsuleFrom = Math.max(nodeFrom, nodeTo - capsule.length);
    const overlapFrom = Math.max(selection.from, capsuleFrom);
    const overlapTo = Math.min(selection.to, nodeTo);
    if (overlapFrom < overlapTo) {
      touchesCapsule = true;
      return false;
    }
    return undefined;
  });

  return touchesCapsule;
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
    const onProtectedTerminalCapsule = this.options.onProtectedTerminalCapsule;
    return [
      new Plugin({
        props: {
          handleDrop(view, event, _slice, moved) {
            if (!moved || !selectionIncludesTerminalCapsule(view)) {
              return false;
            }

            event.preventDefault();
            onProtectedTerminalCapsule();
            return true;
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
