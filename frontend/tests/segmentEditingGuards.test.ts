import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";

import { Schema } from "@tiptap/pm/model";
import { EditorState, NodeSelection, TextSelection } from "@tiptap/pm/state";

import { SegmentEditingGuards } from "../src/components/workspace/workspace-editor/segmentEditingGuards";

const segmentEditingGuardsSource = readFileSync(
  resolve(
    dirname(fileURLToPath(import.meta.url)),
    "../src/components/workspace/workspace-editor/segmentEditingGuards.ts",
  ),
  "utf8",
);
const workspaceEditorHostSource = readFileSync(
  resolve(
    dirname(fileURLToPath(import.meta.url)),
    "../src/components/workspace/WorkspaceEditorHost.vue",
  ),
  "utf8",
);

const schema = new Schema({
  nodes: {
    doc: { content: "block+" },
    paragraph: { content: "inline*", group: "block" },
    text: { group: "inline" },
    pauseBoundary: {
      group: "inline",
      inline: true,
      atom: true,
      selectable: true,
    },
  },
  marks: {
    segmentAnchor: {
      attrs: {
        segmentId: { default: null },
      },
    },
    terminalCapsule: {
      attrs: {
        segmentId: { default: null },
      },
    },
  },
});

function buildDoc() {
  return schema.node("doc", null, [
    schema.node("paragraph", null, [
      schema.text("abc", [
        schema.mark("segmentAnchor", { segmentId: "seg-1" }),
      ]),
      schema.text(".", [
        schema.mark("segmentAnchor", { segmentId: "seg-1" }),
        schema.mark("terminalCapsule", { segmentId: "seg-1" }),
      ]),
      schema.node("pauseBoundary"),
    ]),
  ]);
}

function resolveShortcut(name: "Backspace" | "Delete") {
  const shortcuts = (SegmentEditingGuards as typeof SegmentEditingGuards & {
    config: {
      addKeyboardShortcuts: () => Record<string, (props: { editor: { view: { state: EditorState } } }) => boolean>;
    };
  }).config.addKeyboardShortcuts();

  return shortcuts[name];
}

function runShortcut(
  name: "Backspace" | "Delete",
  selection: TextSelection | NodeSelection,
) {
  const doc = buildDoc();
  const state = EditorState.create({ doc, selection });
  const shortcut = resolveShortcut(name);
  return shortcut({
    editor: {
      view: { state },
    },
  });
}

function resolveDropHandler(onProtectedTerminalCapsule = () => {}) {
  const extension = SegmentEditingGuards.configure({
    onProtectedTerminalCapsule,
  }) as typeof SegmentEditingGuards & {
    options: {
      onProtectedTerminalCapsule: () => void;
    };
    config: {
      addProseMirrorPlugins: (this: { options: { onProtectedTerminalCapsule: () => void } }) => Array<{
        props: {
          handleDrop?: (
            view: { state: EditorState },
            event: DragEvent,
            slice: null,
            moved: boolean,
          ) => boolean;
        };
      }>;
    };
  };

  const plugins = extension.config.addProseMirrorPlugins.call({
    options: extension.options,
  });

  return plugins[0]?.props.handleDrop;
}

function resolvePasteHandler() {
  const extension = SegmentEditingGuards.configure({
    onProtectedTerminalCapsule: () => {},
  }) as typeof SegmentEditingGuards & {
    options: {
      onProtectedTerminalCapsule: () => void;
    };
    config: {
      addProseMirrorPlugins: (this: { options: { onProtectedTerminalCapsule: () => void } }) => Array<{
        props: {
          handlePaste?: (
            view: {
              state: EditorState;
              dispatch: (transaction: unknown) => void;
            },
            event: ClipboardEvent,
          ) => boolean;
        };
      }>;
    };
  };

  const plugins = extension.config.addProseMirrorPlugins.call({
    options: extension.options,
  });

  return plugins[0]?.props.handlePaste;
}

describe("segmentEditingGuards", () => {
  it("Backspace 删除句尾标点时不应误判为命中 pauseBoundary", () => {
    const doc = buildDoc();

    expect(runShortcut("Backspace", TextSelection.create(doc, 4))).toBe(false);
  });

  it("正文与句尾一起被框选时，Backspace 不应整段拦截删除", () => {
    const doc = buildDoc();

    expect(runShortcut("Backspace", TextSelection.create(doc, 2, 4))).toBe(false);
  });

  it("正文与句尾一起被框选时，Delete 也不应整段拦截删除", () => {
    const doc = buildDoc();

    expect(runShortcut("Delete", TextSelection.create(doc, 2, 4))).toBe(false);
  });

  it("Delete 直接命中停顿节点时仍应阻止删除", () => {
    const doc = buildDoc();

    expect(runShortcut("Delete", TextSelection.create(doc, 5))).toBe(true);
    expect(runShortcut("Delete", NodeSelection.create(doc, 5))).toBe(true);
  });

  it("Backspace 直接命中停顿节点时仍应阻止删除", () => {
    const doc = buildDoc();

    expect(runShortcut("Backspace", TextSelection.create(doc, 6))).toBe(true);
    expect(runShortcut("Backspace", NodeSelection.create(doc, 5))).toBe(true);
  });

  it("terminal region 拖放不再被旧句尾保护逻辑拦截", () => {
    const onProtectedTerminalCapsule = vi.fn();
    const handleDrop = resolveDropHandler(onProtectedTerminalCapsule);
    const doc = buildDoc();
    const state = EditorState.create({
      doc,
      selection: TextSelection.create(doc, 3, 4),
    });
    const preventDefault = vi.fn();

    expect(
      handleDrop?.(
        { state } as never,
        { preventDefault } as unknown as DragEvent,
        null,
        true,
      ),
    ).toBe(false);
    expect(preventDefault).not.toHaveBeenCalled();
    expect(onProtectedTerminalCapsule).not.toHaveBeenCalled();
  });

  it("普通文本拖放不应被句末保护误拦截", () => {
    const onProtectedTerminalCapsule = vi.fn();
    const handleDrop = resolveDropHandler(onProtectedTerminalCapsule);
    const doc = buildDoc();
    const state = EditorState.create({
      doc,
      selection: TextSelection.create(doc, 1, 4),
    });
    const preventDefault = vi.fn();

    expect(
      handleDrop?.(
        { state } as never,
        { preventDefault } as unknown as DragEvent,
        null,
        true,
      ),
    ).toBe(false);
    expect(preventDefault).not.toHaveBeenCalled();
    expect(onProtectedTerminalCapsule).not.toHaveBeenCalled();
  });

  it("粘贴多行文本时会走当前的换行标准化路径", () => {
    const handlePaste = resolvePasteHandler();
    const dispatch = vi.fn();
    const state = EditorState.create({ doc: buildDoc() });
    const preventDefault = vi.fn();

    expect(
      handlePaste?.(
        { state, dispatch } as never,
        {
          preventDefault,
          clipboardData: {
            getData: () => "第一行\r\n第二行",
          },
        } as unknown as ClipboardEvent,
      ),
    ).toBe(true);
    expect(preventDefault).toHaveBeenCalledTimes(1);
    expect(dispatch).toHaveBeenCalledTimes(1);
  });

  it("源码里不再保留 splitSegmentTerminalCapsule 句尾软保护路径", () => {
    expect(segmentEditingGuardsSource).not.toContain("splitSegmentTerminalCapsule");
  });

  it("WorkspaceEditorHost 主路径不再引用 terminalCapsuleProtection", () => {
    expect(workspaceEditorHostSource).not.toContain("terminalCapsuleProtection");
    expect(workspaceEditorHostSource).not.toContain("sanitizeWorkspaceViewDocTerminalCapsules");
  });
});
