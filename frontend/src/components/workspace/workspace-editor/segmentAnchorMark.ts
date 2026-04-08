import { Mark, mergeAttributes } from "@tiptap/core";

export const SegmentAnchorMark = Mark.create({
  name: "segmentAnchor",
  inclusive: false,

  addAttributes() {
    return {
      segmentId: { default: null },
    };
  },

  parseHTML() {
    return [{ tag: "span[data-segment-anchor]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "span",
      mergeAttributes(HTMLAttributes, {
        "data-segment-anchor": HTMLAttributes.segmentId,
      }),
      0,
    ];
  },
});
