import { Mark, mergeAttributes } from "@tiptap/core";

export const TerminalCapsuleMark = Mark.create({
  name: "terminalCapsule",
  inclusive: true,

  addAttributes() {
    return {
      segmentId: { default: null },
      terminalSource: { default: null },
    };
  },

  parseHTML() {
    return [{ tag: "span[data-terminal-capsule]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "span",
      mergeAttributes(HTMLAttributes, {
        "data-terminal-capsule": HTMLAttributes.segmentId,
        "data-terminal-source": HTMLAttributes.terminalSource,
      }),
      0,
    ];
  },
});
