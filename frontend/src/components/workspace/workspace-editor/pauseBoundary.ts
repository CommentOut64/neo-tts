import { Node, mergeAttributes } from "@tiptap/core";
import { VueNodeViewRenderer } from "@tiptap/vue-3";

import PauseBoundaryNodeView from "./PauseBoundaryNodeView.vue";

export interface PauseBoundaryOptions {
  onActivateEdge: (edgeId: string | null) => void;
}

export const PauseBoundary = Node.create<PauseBoundaryOptions>({
  name: "pauseBoundary",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,

  addOptions() {
    return {
      onActivateEdge: () => {},
    };
  },

  addAttributes() {
    return {
      edgeId: { default: null },
      leftSegmentId: { default: null },
      rightSegmentId: { default: null },
      pauseDurationSeconds: { default: null },
      boundaryStrategy: { default: null },
      layoutMode: { default: "list" },
      crossBlock: { default: false },
    };
  },

  parseHTML() {
    return [{ tag: "span[data-pause-boundary]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "span",
      mergeAttributes(HTMLAttributes, {
        "data-pause-boundary": "",
        "data-edge-id": HTMLAttributes.edgeId,
      }),
    ];
  },

  addNodeView() {
    return VueNodeViewRenderer(PauseBoundaryNodeView);
  },
});
