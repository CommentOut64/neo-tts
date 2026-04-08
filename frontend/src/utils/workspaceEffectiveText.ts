import type { JSONContent } from "@tiptap/vue-3";

function readNodeText(node: JSONContent | undefined): string {
  if (!node) {
    return "";
  }

  if (typeof node.text === "string") {
    return node.text;
  }

  return (node.content ?? []).map((child) => readNodeText(child)).join("");
}

export function extractWorkspaceEffectiveText(doc: JSONContent): string {
  return (doc.content ?? []).map((node) => readNodeText(node)).join("");
}
