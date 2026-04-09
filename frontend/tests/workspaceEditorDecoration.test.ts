import { describe, expect, it } from "vitest";

import { extractRenderMapFromDoc } from "../src/components/workspace/workspace-editor/extractRenderMapFromDoc";
import {
  buildSegmentDecorationSpecs,
  type SegmentDecorationState,
} from "../src/components/workspace/workspace-editor/segmentDecoration";

describe("workspace editor decoration", () => {
  it("列表式会为单段 paragraph 提取整行范围，供整行高亮使用", () => {
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

    expect(renderMap.segmentBlockRanges).toEqual([
      {
        segmentId: "seg-1",
        from: 0,
        to: 7,
      },
      {
        segmentId: "seg-2",
        from: 7,
        to: 13,
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

  it("列表式 decoration 会输出整行 class，而不是文本 fragment", () => {
    const state = {
      layoutMode: "list",
      renderMap: {
        orderedSegmentIds: ["seg-1", "seg-2"],
        segmentRanges: [],
        segmentBlockRanges: [
          { segmentId: "seg-1", from: 0, to: 7 },
          { segmentId: "seg-2", from: 7, to: 13 },
        ],
        edgeAnchors: [],
      },
      playingId: "seg-1",
      selectedIds: new Set(["seg-2"]),
      dirtyIds: new Set(["seg-1"]),
      dirtyEdgeIds: new Set<string>(),
      isEditing: false,
    } as unknown as SegmentDecorationState;

    const specs = buildSegmentDecorationSpecs(state);

    expect(specs).toHaveLength(2);
    expect(specs[0].from).toBe(0);
    expect(specs[0].to).toBe(7);
    expect(specs[0].attrs.class).toContain("segment-line");
    expect(specs[0].attrs.class).toContain("segment-line-playing");
    expect(specs[0].attrs.class).toContain("segment-line-dirty");
    expect(specs[0].attrs.class).not.toContain("segment-fragment");
    expect(specs[1].attrs.class).toContain("segment-line-selected");
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

  it("列表式编辑态播放段应切为整行绿色背景高亮，并压过 dirty", () => {
    const state = {
      layoutMode: "list",
      renderMap: {
        orderedSegmentIds: ["seg-1"],
        segmentRanges: [],
        segmentBlockRanges: [{ segmentId: "seg-1", from: 0, to: 7 }],
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
    expect(specs[0].attrs.class).toContain("segment-line");
    expect(specs[0].attrs.class).toContain("segment-line-dirty");
    expect(specs[0].attrs.class).toContain("segment-line-editing-playing");
    expect(specs[0].attrs.class).not.toContain("segment-line-playing");
  });

  it("列表式拖拽时会给源段和落点段叠加 reorder class", () => {
    const state = {
      layoutMode: "list",
      renderMap: {
        orderedSegmentIds: ["seg-1", "seg-2"],
        segmentRanges: [],
        segmentBlockRanges: [
          { segmentId: "seg-1", from: 0, to: 7 },
          { segmentId: "seg-2", from: 7, to: 13 },
        ],
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

    expect(specs[0].attrs.class).toContain("segment-line-reorder-source");
    expect(specs[1].attrs.class).toContain("segment-line-drop-before");
    expect(specs[1].attrs.class).not.toContain("segment-line-drop-swap");
  });

  it("列表式提交重排时会附加 submitting class", () => {
    const state = {
      layoutMode: "list",
      renderMap: {
        orderedSegmentIds: ["seg-1"],
        segmentRanges: [],
        segmentBlockRanges: [{ segmentId: "seg-1", from: 0, to: 7 }],
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

    expect(specs).toHaveLength(1);
    expect(specs[0].attrs.class).toContain("segment-line-submitting");
  });
});
