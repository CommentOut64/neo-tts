import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { extractRenderMapFromDoc } from "../src/components/workspace/workspace-editor/extractRenderMapFromDoc";
import {
  buildSegmentDecorationSpecs,
  type SegmentDecorationState,
} from "../src/components/workspace/workspace-editor/segmentDecoration";

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

describe("workspace editor decoration", () => {
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
