import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { extractRenderMapFromDoc } from "../src/components/workspace/workspace-editor/extractRenderMapFromDoc";
import {
  buildLiveSegmentDecorationSpecsFromDoc,
  buildSegmentDecorationSpecs,
  type SegmentDecorationState,
} from "../src/components/workspace/workspace-editor/segmentDecoration";
import type { PlaybackCursor } from "../src/types/editSession";

const extractRenderMapSource = readFileSync(
  resolve(
    dirname(fileURLToPath(import.meta.url)),
    "../src/components/workspace/workspace-editor/extractRenderMapFromDoc.ts",
  ),
  "utf8",
);
const segmentDecorationSource = readFileSync(
  resolve(
    dirname(fileURLToPath(import.meta.url)),
    "../src/components/workspace/workspace-editor/segmentDecoration.ts",
  ),
  "utf8",
);
const layoutTypesSource = readFileSync(
  resolve(
    dirname(fileURLToPath(import.meta.url)),
    "../src/components/workspace/workspace-editor/layoutTypes.ts",
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

describe("workspace editor decoration", () => {
  function buildPlaybackCursorState(
    playingCursor: PlaybackCursor | null,
  ): SegmentDecorationState {
    return {
      layoutMode: "composition",
      renderMap: {
        orderedSegmentIds: ["seg-1", "seg-2"],
        segmentRanges: [
          { segmentId: "seg-1", from: 1, to: 5 },
          { segmentId: "seg-2", from: 6, to: 10 },
        ],
        edgeAnchors: [],
      },
      showReorderHandle: false,
      playingId: null,
      playingCursor,
      selectedIds: new Set<string>(),
      dirtyIds: new Set<string>(),
      dirtyEdgeIds: new Set<string>(),
      isEditing: false,
    } as unknown as SegmentDecorationState;
  }

  it("组合视图 renderMap 仍提取 segmentRanges 和 edgeAnchors，但不再保留列表式 block range", () => {
    const renderMap = (extractRenderMapFromDoc as any)(
      {
        type: "doc",
        content: [
          {
            type: "paragraph",
            content: [
              {
                type: "text",
                text: "第一段。",
                marks: [{ type: "segmentAnchor", attrs: { segmentId: "seg-1" } }],
              },
              {
                type: "pauseBoundary",
                attrs: {
                  edgeId: "edge-1",
                  leftSegmentId: "seg-1",
                  rightSegmentId: "seg-2",
                  layoutMode: "list",
                  crossBlock: false,
                },
              },
            ],
          },
          {
            type: "paragraph",
            content: [
              {
                type: "text",
                text: "第二段。",
                marks: [{ type: "segmentAnchor", attrs: { segmentId: "seg-2" } }],
              },
            ],
          },
        ],
      },
      ["seg-1", "seg-2"],
      "list",
    );

    expect("segmentBlockRanges" in renderMap).toBe(false);
    expect(renderMap.edgeAnchors).toEqual([
      {
        edgeId: "edge-1",
        leftSegmentId: "seg-1",
        rightSegmentId: "seg-2",
        from: 5,
        to: 6,
        layoutMode: "list",
        crossBlock: false,
      },
    ]);
  });

  it("extractRenderMapFromDoc 能从 segmentAnchor 和 pauseBoundary 提取 range / anchor", () => {
    const renderMap = extractRenderMapFromDoc(
      {
        type: "doc",
        content: [
          {
            type: "paragraph",
            content: [
              {
                type: "text",
                text: "第一段。",
                marks: [{ type: "segmentAnchor", attrs: { segmentId: "seg-1" } }],
              },
              {
                type: "pauseBoundary",
                attrs: {
                  edgeId: "edge-1",
                  leftSegmentId: "seg-1",
                  rightSegmentId: "seg-2",
                  layoutMode: "composition",
                  crossBlock: false,
                },
              },
              {
                type: "text",
                text: "第二段。",
                marks: [{ type: "segmentAnchor", attrs: { segmentId: "seg-2" } }],
              },
              {
                type: "pauseBoundary",
                attrs: {
                  edgeId: "edge-2",
                  leftSegmentId: "seg-2",
                  rightSegmentId: "seg-3",
                  layoutMode: "composition",
                  crossBlock: true,
                },
              },
            ],
          },
          {
            type: "paragraph",
            content: [
              {
                type: "text",
                text: "第三段。",
                marks: [{ type: "segmentAnchor", attrs: { segmentId: "seg-3" } }],
              },
            ],
          },
        ],
      },
      ["seg-1", "seg-2", "seg-3"],
    );

    expect(renderMap.orderedSegmentIds).toEqual(["seg-1", "seg-2", "seg-3"]);
    expect(renderMap.segmentRanges).toHaveLength(3);
    expect(renderMap.segmentRanges.map((range) => range.segmentId)).toEqual([
      "seg-1",
      "seg-2",
      "seg-3",
    ]);
    expect(renderMap.segmentRanges[0]).toMatchObject({
      segmentId: "seg-1",
      from: 1,
      to: 5,
    });
    expect(renderMap.segmentRanges[0].to).toBeLessThan(renderMap.segmentRanges[1].from);
    expect(renderMap.edgeAnchors).toEqual([
      {
        edgeId: "edge-1",
        leftSegmentId: "seg-1",
        rightSegmentId: "seg-2",
        from: 5,
        to: 6,
        layoutMode: "composition",
        crossBlock: false,
      },
      {
        edgeId: "edge-2",
        leftSegmentId: "seg-2",
        rightSegmentId: "seg-3",
        from: 10,
        to: 11,
        layoutMode: "composition",
        crossBlock: true,
      },
    ]);
  });

  it("buildSegmentDecorationSpecs 会按 playing / selected / dirty 叠加 class，且同段落多 segment 不串色", () => {
    const renderMap = extractRenderMapFromDoc(
      {
        type: "doc",
        content: [
          {
            type: "paragraph",
            content: [
              {
                type: "text",
                text: "第一段。",
                marks: [{ type: "segmentAnchor", attrs: { segmentId: "seg-1" } }],
              },
              {
                type: "pauseBoundary",
                attrs: {
                  edgeId: "edge-1",
                  leftSegmentId: "seg-1",
                  rightSegmentId: "seg-2",
                  layoutMode: "composition",
                  crossBlock: false,
                },
              },
              {
                type: "text",
                text: "第二段。",
                marks: [{ type: "segmentAnchor", attrs: { segmentId: "seg-2" } }],
              },
            ],
          },
        ],
      },
      ["seg-1", "seg-2"],
    );

    const state: SegmentDecorationState = {
      layoutMode: "composition",
      renderMap,
      playingId: "seg-1",
      selectedIds: new Set(["seg-2"]),
      dirtyIds: new Set(["seg-1"]),
      dirtyEdgeIds: new Set<string>(),
      isEditing: false,
    };

    const specs = buildSegmentDecorationSpecs(state);
    expect(specs).toHaveLength(2);

    const bySegmentId = Object.fromEntries(
      specs.map((spec) => [spec.attrs["data-segment-id"], spec]),
    );

    expect(bySegmentId["seg-1"].attrs.class).toContain("segment-fragment");
    expect(bySegmentId["seg-1"].attrs.class).toContain("segment-playing");
    expect(bySegmentId["seg-1"].attrs.class).toContain("segment-dirty");
    expect(bySegmentId["seg-1"].from).toBe(1);
    expect(bySegmentId["seg-1"].to).toBe(5);
    expect(bySegmentId["seg-2"].attrs.class).toContain("segment-selected");
    expect(bySegmentId["seg-1"].to).toBeLessThan(bySegmentId["seg-2"].from);
  });

  it("只有 playingCursor.kind === segment 时才高亮对应段", () => {
    const segmentState = buildPlaybackCursorState({
      sample: 2,
      kind: "segment",
      segmentId: "seg-1",
      edgeId: null,
      leftSegmentId: null,
      rightSegmentId: null,
      spanStartSample: 0,
      spanEndSample: 3,
      progressInSpan: 2 / 3,
    });

    const boundaryState = buildPlaybackCursorState({
      sample: 3,
      kind: "boundary",
      segmentId: null,
      edgeId: "edge-1",
      leftSegmentId: "seg-1",
      rightSegmentId: "seg-2",
      spanStartSample: 3,
      spanEndSample: 4,
      progressInSpan: 0,
    });

    const pauseState = buildPlaybackCursorState({
      sample: 4,
      kind: "pause",
      segmentId: null,
      edgeId: "edge-1",
      leftSegmentId: "seg-1",
      rightSegmentId: "seg-2",
      spanStartSample: 4,
      spanEndSample: 6,
      progressInSpan: 0,
    });

    const beforeStartState = buildPlaybackCursorState({
      sample: -1,
      kind: "before_start",
      segmentId: null,
      edgeId: null,
      leftSegmentId: null,
      rightSegmentId: null,
      spanStartSample: 0,
      spanEndSample: 0,
      progressInSpan: 0,
    });

    const endedState = buildPlaybackCursorState({
      sample: 9,
      kind: "ended",
      segmentId: null,
      edgeId: null,
      leftSegmentId: null,
      rightSegmentId: null,
      spanStartSample: 9,
      spanEndSample: 9,
      progressInSpan: 1,
    });

    const segmentSpecs = buildSegmentDecorationSpecs(segmentState);
    const boundarySpecs = buildSegmentDecorationSpecs(boundaryState);
    const pauseSpecs = buildSegmentDecorationSpecs(pauseState);
    const beforeStartSpecs = buildSegmentDecorationSpecs(beforeStartState);
    const endedSpecs = buildSegmentDecorationSpecs(endedState);

    expect(segmentSpecs[0].attrs.class).toContain("segment-playing");
    expect(segmentSpecs[1].attrs.class).not.toContain("segment-playing");

    for (const specs of [
      boundarySpecs,
      pauseSpecs,
      beforeStartSpecs,
      endedSpecs,
    ]) {
      expect(specs[0].attrs.class).not.toContain("segment-playing");
      expect(specs[1].attrs.class).not.toContain("segment-playing");
    }
  });

  it("列表式重构后，源码中不应再保留旧的 renderMap block range 路径", () => {
    expect(extractRenderMapSource).not.toContain("segmentBlockRanges");
    expect(extractRenderMapSource).not.toContain("collectParagraphSegmentIds");
    expect(layoutTypesSource).not.toContain("SegmentBlockRange");
    expect(layoutTypesSource).not.toContain("segmentBlockRanges");
    expect(segmentDecorationSource).not.toContain("state.renderMap.segmentBlockRanges");
  });

  it("列表式基础状态不再走旧的纯 spec 路径，而由 node decoration / NodeView 承担", () => {
    const state = {
      layoutMode: "list",
      renderMap: {
        orderedSegmentIds: ["seg-1", "seg-2"],
        segmentRanges: [],
        edgeAnchors: [],
      },
      playingId: "seg-1",
      selectedIds: new Set(["seg-2"]),
      dirtyIds: new Set(["seg-1"]),
      dirtyEdgeIds: new Set<string>(),
      isEditing: false,
    } as unknown as SegmentDecorationState;

    const specs = buildSegmentDecorationSpecs(state);

    expect(specs).toEqual([]);
  });

  it("组合式编辑态不应保留 dirty 背景高亮", () => {
    const state = {
      layoutMode: "composition",
      renderMap: {
        orderedSegmentIds: ["seg-1"],
        segmentRanges: [{ segmentId: "seg-1", from: 1, to: 5 }],
        segmentBlockRanges: [],
        edgeAnchors: [],
      },
      playingId: null,
      selectedIds: new Set<string>(),
      dirtyIds: new Set(["seg-1"]),
      dirtyEdgeIds: new Set<string>(),
      isEditing: true,
    } as unknown as SegmentDecorationState;

    const specs = buildSegmentDecorationSpecs(state);

    expect(specs).toHaveLength(1);
    expect(specs[0].attrs.class).toContain("segment-fragment");
    expect(specs[0].attrs.class).not.toContain("segment-dirty");
  });

  it("组合式编辑态播放段应切为绿色背景高亮，并覆盖 dirty 视觉", () => {
    const state = {
      layoutMode: "composition",
      renderMap: {
        orderedSegmentIds: ["seg-1"],
        segmentRanges: [{ segmentId: "seg-1", from: 1, to: 5 }],
        segmentBlockRanges: [],
        edgeAnchors: [],
      },
      playingId: "seg-1",
      selectedIds: new Set<string>(),
      dirtyIds: new Set(["seg-1"]),
      dirtyEdgeIds: new Set<string>(),
      isEditing: true,
    } as unknown as SegmentDecorationState;

    const specs = buildSegmentDecorationSpecs(state);

    expect(specs).toHaveLength(1);
    expect(specs[0].attrs.class).toContain("segment-editing-playing");
    expect(specs[0].attrs.class).not.toContain("segment-playing");
    expect(specs[0].attrs.class).not.toContain("segment-dirty");
  });

  it("组合式高亮应从当前文档实时提取并合并同段 stem 与句末标点", () => {
    const state = {
      layoutMode: "composition",
      renderMap: {
        orderedSegmentIds: ["seg-1", "seg-2"],
        segmentRanges: [
          { segmentId: "seg-1", from: 1, to: 3 },
          { segmentId: "seg-1", from: 3, to: 4 },
          { segmentId: "seg-2", from: 4, to: 6 },
        ],
        edgeAnchors: [],
      },
      playingId: "seg-1",
      selectedIds: new Set<string>(),
      dirtyIds: new Set<string>(),
      dirtyEdgeIds: new Set<string>(),
      isEditing: false,
    } as unknown as SegmentDecorationState;

    const editedDoc = {
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [
            {
              type: "text",
              text: "新增正文",
              marks: [{ type: "segmentAnchor", attrs: { segmentId: "seg-1" } }],
            },
            {
              type: "text",
              text: "。",
              marks: [
                { type: "segmentAnchor", attrs: { segmentId: "seg-1" } },
                { type: "terminalCapsule", attrs: { segmentId: "seg-1" } },
              ],
            },
            {
              type: "text",
              text: "第二段。",
              marks: [{ type: "segmentAnchor", attrs: { segmentId: "seg-2" } }],
            },
          ],
        },
      ],
    };

    const specs = buildLiveSegmentDecorationSpecsFromDoc(editedDoc, state);
    const seg1Specs = specs.filter((spec) => spec.attrs["data-segment-id"] === "seg-1");
    const seg2Spec = specs.find((spec) => spec.attrs["data-segment-id"] === "seg-2");

    expect(specs).toHaveLength(3);
    expect(seg1Specs).toHaveLength(2);
    expect(seg1Specs[0]).toMatchObject({
      from: 1,
      to: 5,
    });
    expect(seg1Specs[0].attrs.class).toContain("segment-fragment-start");
    expect(seg1Specs[0].attrs.class).toContain("segment-playing");
    expect(seg1Specs[1]).toMatchObject({
      from: 5,
      to: 6,
    });
    expect(seg1Specs[1].attrs.class).toContain("segment-fragment-end");
    expect(seg1Specs[1].attrs.class).toContain("segment-playing");
    expect(seg2Spec).toMatchObject({
      from: 6,
      to: 10,
    });
    expect(seg2Spec?.attrs.class).toContain("segment-fragment-single");
  });

  it("组合式 inline 高亮样式应恢复整体圆角，并只在同段首尾保留外侧圆角", () => {
    const segmentFragmentRule = workspaceEditorHostSource.match(
      /:deep\(\.segment-fragment\) \{[\s\S]*?\n\}/,
    )?.[0] ?? "";
    const singleRule = workspaceEditorHostSource.match(
      /:deep\(\.segment-fragment-single\) \{[\s\S]*?\n\}/,
    )?.[0] ?? "";
    const startRule = workspaceEditorHostSource.match(
      /:deep\(\.segment-fragment-start\) \{[\s\S]*?\n\}/,
    )?.[0] ?? "";
    const endRule = workspaceEditorHostSource.match(
      /:deep\(\.segment-fragment-end\) \{[\s\S]*?\n\}/,
    )?.[0] ?? "";
    const dirtyRule = workspaceEditorHostSource.match(
      /:deep\(\.segment-dirty\) \{[\s\S]*?\n\}/,
    )?.[0] ?? "";
    const editingPlayingRule = workspaceEditorHostSource.match(
      /:deep\(\.segment-editing-playing\) \{[\s\S]*?\n\}/,
    )?.[0] ?? "";

    expect(segmentFragmentRule).toContain("border-radius: 0;");
    expect(segmentFragmentRule).toContain("margin: 0;");
    expect(segmentFragmentRule).toContain("padding: 1px 0;");
    expect(singleRule).toContain("border-radius: 4px;");
    expect(singleRule).toContain("margin: 0 -2px;");
    expect(singleRule).toContain("padding: 1px 2px;");
    expect(startRule).toContain("border-top-left-radius: 4px;");
    expect(startRule).toContain("border-bottom-left-radius: 4px;");
    expect(startRule).toContain("margin-left: -2px;");
    expect(startRule).toContain("padding-left: 2px;");
    expect(endRule).toContain("border-top-right-radius: 4px;");
    expect(endRule).toContain("border-bottom-right-radius: 4px;");
    expect(endRule).toContain("margin-right: -2px;");
    expect(endRule).toContain("padding-right: 2px;");
    expect(dirtyRule).toContain("--segment-fragment-shadow-color");
    expect(editingPlayingRule).toContain("--segment-fragment-shadow-color");
  });

  it("列表式编辑态样式不再通过 buildSegmentDecorationSpecs 直接生成", () => {
    const state = {
      layoutMode: "list",
      renderMap: {
        orderedSegmentIds: ["seg-1"],
        segmentRanges: [],
        edgeAnchors: [],
      },
      playingId: "seg-1",
      selectedIds: new Set<string>(),
      dirtyIds: new Set(["seg-1"]),
      dirtyEdgeIds: new Set<string>(),
      isEditing: true,
    } as unknown as SegmentDecorationState;

    const specs = buildSegmentDecorationSpecs(state);

    expect(specs).toEqual([]);
  });

  it("列表式拖拽态不再通过旧的 list spec 数组暴露", () => {
    const state = {
      layoutMode: "list",
      renderMap: {
        orderedSegmentIds: ["seg-1", "seg-2"],
        segmentRanges: [],
        edgeAnchors: [],
      },
      playingId: null,
      selectedIds: new Set<string>(),
      dirtyIds: new Set<string>(),
      dirtyEdgeIds: new Set<string>(),
      isEditing: false,
      draggingSegmentId: "seg-1",
      dropTargetSegmentId: "seg-2",
      dropIntent: "insert-before",
      isSubmittingReorder: false,
    } as unknown as SegmentDecorationState;

    const specs = buildSegmentDecorationSpecs(state);

    expect(specs).toEqual([]);
  });

  it("列表式提交重排的状态类也改由 node decoration / NodeView 路径承担", () => {
    const state = {
      layoutMode: "list",
      renderMap: {
        orderedSegmentIds: ["seg-1"],
        segmentRanges: [],
        edgeAnchors: [],
      },
      playingId: null,
      selectedIds: new Set<string>(),
      dirtyIds: new Set<string>(),
      dirtyEdgeIds: new Set<string>(),
      isEditing: false,
      draggingSegmentId: null,
      dropTargetSegmentId: null,
      dropIntent: null,
      isSubmittingReorder: true,
    } as unknown as SegmentDecorationState;

    const specs = buildSegmentDecorationSpecs(state);

    expect(specs).toEqual([]);
  });
});
