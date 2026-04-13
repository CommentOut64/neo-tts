import { describe, expect, it } from "vitest";

import {
  extractOrderedSegmentTextsFromWorkspaceViewDoc,
  normalizeWorkspaceViewDocToSourceDoc,
} from "../src/components/workspace/workspace-editor/sourceDocNormalizer";
import { splitSegmentTerminalCapsule } from "../src/utils/segmentTextDisplay";

describe("workspace list view normalizer", () => {
  it("列表式会按 segmentBlock.attrs.segmentId 提取文本，而不是依赖 segmentAnchor", () => {
    expect(
      extractOrderedSegmentTextsFromWorkspaceViewDoc(
        {
          type: "doc",
          content: [
            {
              type: "segmentBlock",
              attrs: { segmentId: "seg-1" },
              content: [
                { type: "text", text: "新的第一段" },
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
              type: "segmentBlock",
              attrs: { segmentId: "seg-2" },
              content: [{ type: "text", text: "第二段" }],
            },
          ],
        },
        ["seg-1", "seg-2"],
      ),
    ).toEqual([
      { segmentId: "seg-1", text: "新的第一段" },
      { segmentId: "seg-2", text: "第二段" },
    ]);
  });

  it("列表式 segmentBlock 缺失或篡改 segmentId 时会明确报错", () => {
    expect(() =>
      extractOrderedSegmentTextsFromWorkspaceViewDoc(
        {
          type: "doc",
          content: [
            {
              type: "segmentBlock",
              attrs: {},
              content: [{ type: "text", text: "第一段" }],
            },
          ],
        },
        ["seg-1"],
      ),
    ).toThrow(/segmentId/i);
  });

  it("列表式 segmentBlock 的 attrs.segmentId 被篡改时会拒绝归并", () => {
    expect(() =>
      extractOrderedSegmentTextsFromWorkspaceViewDoc(
        {
          type: "doc",
          content: [
            {
              type: "segmentBlock",
              attrs: { segmentId: "seg-1-corrupted" },
              content: [
                {
                  type: "text",
                  text: "第一段",
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
              type: "segmentBlock",
              attrs: { segmentId: "seg-2" },
              content: [
                {
                  type: "text",
                  text: "第二段",
                  marks: [{ type: "segmentAnchor", attrs: { segmentId: "seg-2" } }],
                },
              ],
            },
          ],
        },
        ["seg-1", "seg-2"],
      ),
    ).toThrow(/segmentId/i);
  });

  it("组合视图仍按 segmentAnchor 聚合，并能规范化回 canonical sourceDoc", () => {
    expect(
      normalizeWorkspaceViewDocToSourceDoc({
        viewDoc: {
          type: "doc",
          content: [
            {
              type: "paragraph",
              content: [
                {
                  type: "text",
                  text: "第一段",
                  marks: [{ type: "segmentAnchor", attrs: { segmentId: "seg-1" } }],
                },
                {
                  type: "pauseBoundary",
                  attrs: {
                    edgeId: "edge-1",
                    leftSegmentId: "seg-1",
                    rightSegmentId: "seg-2",
                    pauseDurationSeconds: 0.3,
                    boundaryStrategy: "crossfade",
                    layoutMode: "composition",
                    crossBlock: false,
                  },
                },
                {
                  type: "text",
                  text: "第二段",
                  marks: [{ type: "segmentAnchor", attrs: { segmentId: "seg-2" } }],
                },
              ],
            },
          ],
        },
        orderedSegmentIds: ["seg-1", "seg-2"],
        edges: [
          {
            edgeId: "edge-1",
            leftSegmentId: "seg-1",
            rightSegmentId: "seg-2",
            pauseDurationSeconds: 0.3,
            boundaryStrategy: "crossfade",
          },
        ],
      }),
    ).toMatchObject({
      type: "doc",
      content: [
        {
          type: "segmentBlock",
          attrs: { segmentId: "seg-1" },
        },
        {
          type: "segmentBlock",
          attrs: { segmentId: "seg-2" },
        },
      ],
    });
  });

  it("列表式提取的段文本会保留完整句尾胶囊", () => {
    const extracted = extractOrderedSegmentTextsFromWorkspaceViewDoc(
      {
        type: "doc",
        content: [
          {
            type: "segmentBlock",
            attrs: { segmentId: "seg-1" },
            content: [{ type: "text", text: "第一段？！」" }],
          },
        ],
      },
      ["seg-1"],
    );

    expect(extracted).toEqual([{ segmentId: "seg-1", text: "第一段？！」" }]);
    expect(splitSegmentTerminalCapsule(extracted[0]?.text ?? "")).toEqual({
      stem: "第一段",
      terminal: "？！",
      closerSuffix: "」",
      capsule: "？！」",
    });
  });
});
