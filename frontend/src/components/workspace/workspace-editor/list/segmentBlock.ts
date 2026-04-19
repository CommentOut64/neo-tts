import { Node, mergeAttributes } from "@tiptap/core";
import { VueNodeViewRenderer } from "@tiptap/vue-3";

import SegmentBlockNodeView from "./SegmentBlockNodeView.vue";

export const SegmentBlock = Node.create({
  name: "segmentBlock",
  group: "block",
  content: "inline*",
  defining: true,
  isolating: true,
  selectable: false,

  addAttributes() {
    return {
      segmentId: { default: null },
    };
  },

  parseHTML() {
    return [{ tag: "div[data-segment-block]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "div",
      mergeAttributes(HTMLAttributes, {
        "data-segment-block": "",
        "data-segment-id": HTMLAttributes.segmentId,
      }),
      0,
    ];
  },

  addNodeView() {
    return VueNodeViewRenderer(SegmentBlockNodeView);
  },
});
