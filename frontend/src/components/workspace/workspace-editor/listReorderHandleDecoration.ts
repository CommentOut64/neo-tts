import { Extension } from "@tiptap/core";
import { Plugin } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

import type { WorkspaceEditorLayoutMode, WorkspaceRenderMap } from "./layoutTypes";
import type { DragReorderMode } from "./listReorderTypes";

export interface ListReorderHandleDecorationState {
  layoutMode: WorkspaceEditorLayoutMode;
  renderMap: WorkspaceRenderMap | null;
  selectedIds: Set<string>;
  draggingSegmentId: string | null;
  mode: DragReorderMode;
}

function buildHandleWidget(input: {
  segmentId: string;
  lineNumber: number;
  isSelected: boolean;
  isDragging: boolean;
}) {
  const root = document.createElement("span");
  root.className = "segment-reorder-handle";
  if (input.isSelected) {
    root.classList.add("is-selected");
  }
  if (input.isDragging) {
    root.classList.add("is-dragging");
  }
  root.setAttribute("contenteditable", "false");
  root.setAttribute("draggable", "false");
  root.setAttribute("data-segment-handle-for", input.segmentId);
  root.setAttribute("data-line-number", String(input.lineNumber));

  const lineNumber = document.createElement("span");
  lineNumber.className = "segment-reorder-line-number";
  lineNumber.textContent = String(input.lineNumber).padStart(2, "0");

  const grip = document.createElement("span");
  grip.className = "segment-reorder-grip";
  grip.setAttribute("aria-hidden", "true");
  grip.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-grip-vertical"><circle cx="9" cy="12" r="1"/><circle cx="9" cy="5" r="1"/><circle cx="9" cy="19" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="15" cy="5" r="1"/><circle cx="15" cy="19" r="1"/></svg>`;
  root.append(lineNumber, grip);
  return root;
}

function buildHandleDecorations(state: ListReorderHandleDecorationState | null) {
  if (!state || state.layoutMode !== "list" || !state.renderMap) {
    return [] as Decoration[];
  }

  return state.renderMap.segmentBlockRanges.map((range, index) =>
    Decoration.widget(
      range.from + 1,
      () =>
        buildHandleWidget({
          segmentId: range.segmentId,
          lineNumber: index + 1,
          isSelected: state.selectedIds.has(range.segmentId),
          isDragging:
            state.mode === "dragging" &&
            state.draggingSegmentId === range.segmentId,
        }),
      {
        side: -1,
      },
    ),
  );
}

export const ListReorderHandleDecoration = Extension.create<
  Record<string, never>,
  { state: ListReorderHandleDecorationState | null }
>({
  name: "listReorderHandleDecoration",

  addStorage() {
    return {
      state: null as ListReorderHandleDecorationState | null,
    };
  },

  addProseMirrorPlugins() {
    const extensionStorage = this.storage;

    return [
      new Plugin({
        props: {
          decorations(editorState) {
            const decorations = buildHandleDecorations(extensionStorage.state);
            return decorations.length > 0
              ? DecorationSet.create(editorState.doc, decorations)
              : DecorationSet.empty;
          },
        },
      }),
    ];
  },
});
