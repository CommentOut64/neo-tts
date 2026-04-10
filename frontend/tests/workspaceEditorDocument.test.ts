import { describe, expect, it } from "vitest";

import type { WorkspaceSemanticDocument } from "../src/components/workspace/workspace-editor/layoutTypes";
import { buildCompositionLayoutDocument } from "../src/components/workspace/workspace-editor/buildCompositionLayoutDocument";
import { buildListLayoutDocument } from "../src/components/workspace/workspace-editor/buildListLayoutDocument";
import {
  collectSegmentDraftChanges,
  normalizeEditorPastedText,
} from "../src/components/workspace/workspace-editor/documentModel";
import { SegmentAnchorMark } from "../src/components/workspace/workspace-editor/segmentAnchorMark";
import {
  extractOrderedSegmentTextsFromWorkspaceViewDoc,
  normalizeWorkspaceViewDocToSourceDoc,
} from "../src/components/workspace/workspace-editor/sourceDocNormalizer";

function createSemanticDocument(): WorkspaceSemanticDocument {
  return {
    segmentOrder: ["seg-1", "seg-2", "seg-3"],
    segmentsById: {
      "seg-1": {
        segmentId: "seg-1",
        orderKey: 1,
        text: "第一段。",
        renderStatus: "completed",
        isDirty: false,
      },
      "seg-2": {
        segmentId: "seg-2",
        orderKey: 2,
        text: "第二段。",
        renderStatus: "completed",
        isDirty: false,
      },
      "seg-3": {
        segmentId: "seg-3",
        orderKey: 3,
        text: "第三段。",
        renderStatus: "completed",
        isDirty: false,
      },
    },
    edgesByLeftSegmentId: {
      "seg-1": {
        edgeId: "edge-1",
        leftSegmentId: "seg-1",
        rightSegmentId: "seg-2",
        pauseDurationSeconds: 0.3,
        boundaryStrategy: "crossfade",
      },
      "seg-2": {
        edgeId: "edge-2",
        leftSegmentId: "seg-2",
        rightSegmentId: "seg-3",
        pauseDurationSeconds: 0.5,
        boundaryStrategy: "crossfade",
      },
    },
    sourceBlocks: [
      {
        blockId: "block-1",
        rawLineText: "第一段。第二段。",
        segmentIds: ["seg-1", "seg-2"],
      },
      {
        blockId: "block-2",
        rawLineText: "第三段。",
        segmentIds: ["seg-3"],
      },
    ],
    compositionAvailability: {
      ready: true,
      reason: null,
    },
  };
}

describe("workspace editor document model", () => {
  it("segmentAnchor mark 在编辑态必须保持 inclusive，避免新输入字符丢失锚点", () => {
    expect((SegmentAnchorMark as any).config.inclusive).toBe(true);
  });

  it("列表式 builder 会输出 segmentBlock，并用节点 attrs 承担段级映射", () => {
    const semanticDocument = createSemanticDocument();
    const plan = buildListLayoutDocument(semanticDocument);
    expect(plan.layoutMode).toBe("list");
    expect(plan.doc.type).toBe("doc");
    expect(plan.doc.content).toHaveLength(3);
    expect(plan.doc.content?.map((node) => node.type)).toEqual([
      "segmentBlock",
      "segmentBlock",
      "segmentBlock",
    ]);
    expect(
      plan.doc.content?.map((node) => node.attrs?.segmentId),
    ).toEqual(semanticDocument.segmentOrder);
    expect(plan.doc.content?.[0]?.content?.at(-1)).toEqual({
      type: "pauseBoundary",
      attrs: {
        edgeId: "edge-1",
        leftSegmentId: "seg-1",
        rightSegmentId: "seg-2",
        pauseDurationSeconds: 0.3,
        boundaryStrategy: "crossfade",
        layoutMode: "list",
        crossBlock: false,
      },
    });
    expect(plan.doc.content?.[2]?.content?.at(-1)?.type).toBe("text");
  });

  it("组合式 builder 可以在同一段落内放多个 segment，并标记跨行 edge", () => {
    const plan = buildCompositionLayoutDocument(createSemanticDocument());

    expect(plan.layoutMode).toBe("composition");
    expect(plan.doc).toEqual({
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
                pauseDurationSeconds: 0.3,
                boundaryStrategy: "crossfade",
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
                pauseDurationSeconds: 0.5,
                boundaryStrategy: "crossfade",
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
    });
  });

  it("组合式 builder 在 source_text 失配后仍会生成组合式视图，而不是退回列表式", () => {
    const plan = buildCompositionLayoutDocument({
      segmentOrder: ["seg-1", "seg-2"],
      segmentsById: {
        "seg-1": {
          segmentId: "seg-1",
          orderKey: 1,
          text: "第一段。",
          renderStatus: "completed",
          isDirty: false,
        },
        "seg-2": {
          segmentId: "seg-2",
          orderKey: 2,
          text: "第二段。",
          renderStatus: "completed",
          isDirty: false,
        },
      },
      edgesByLeftSegmentId: {
        "seg-1": {
          edgeId: "edge-1",
          leftSegmentId: "seg-1",
          rightSegmentId: "seg-2",
          pauseDurationSeconds: 0.3,
          boundaryStrategy: "crossfade",
        },
      },
      sourceBlocks: [
        {
          blockId: "working-copy-block-1",
          rawLineText: "第一段。第二段。",
          segmentIds: ["seg-1", "seg-2"],
        },
      ],
      compositionAvailability: {
        ready: true,
        reason: "source_text_mismatch",
      },
    });

    expect(plan.layoutMode).toBe("composition");
    expect(plan.doc).toEqual({
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
                pauseDurationSeconds: 0.3,
                boundaryStrategy: "crossfade",
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
    });
  });

  it("会把组合式编辑视图规范化回列表形 canonical sourceDoc", () => {
    const semanticDocument = createSemanticDocument();
    const compositionView = buildCompositionLayoutDocument(semanticDocument);

    expect(
      normalizeWorkspaceViewDocToSourceDoc({
        viewDoc: compositionView.doc,
        orderedSegmentIds: semanticDocument.segmentOrder,
        edges: Object.values(semanticDocument.edgesByLeftSegmentId),
      }),
    ).toEqual(
      buildListLayoutDocument({
        ...semanticDocument,
        sourceBlocks: semanticDocument.segmentOrder.map((segmentId, index) => ({
          blockId: `canonical-block-${index + 1}`,
          rawLineText: semanticDocument.segmentsById[segmentId]?.text ?? "",
          segmentIds: [segmentId],
        })),
      }).doc,
    );
  });

  it("编辑中出现临时未带 segmentAnchor 的文本节点时，仍能归并回相邻 segment", () => {
    expect(
      extractOrderedSegmentTextsFromWorkspaceViewDoc(
        {
          type: "doc",
          content: [
            {
              type: "paragraph",
              content: [
                { type: "text", text: "新" },
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
                  },
                },
                { type: "text", text: "更" },
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
    ).toEqual([
      { segmentId: "seg-1", text: "新第一段" },
      { segmentId: "seg-2", text: "更第二段" },
    ]);
  });

  it("提交编辑时会按 segmentAnchor 聚合文本，并对比后端文本收集变更", () => {
    const changes = collectSegmentDraftChanges(
      {
        type: "doc",
        content: [
          {
            type: "paragraph",
            content: [
              {
                type: "text",
                text: "新的",
                marks: [{ type: "segmentAnchor", attrs: { segmentId: "seg-1" } }],
              },
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
      ["seg-1", "seg-2"],
      (segmentId) =>
        ({
          "seg-1": "第一段",
          "seg-2": "第二段",
        })[segmentId] ?? "",
    );

    expect(changes.changedDrafts).toEqual([["seg-1", "新的第一段"]]);
    expect(changes.clearedSegmentIds).toEqual(["seg-2"]);
  });

  it("segmentAnchor 丢失时拒绝提交，避免错位回写", () => {
    expect(() =>
      collectSegmentDraftChanges(
        {
          type: "doc",
          content: [
            {
              type: "paragraph",
              content: [{ type: "text", text: "第一段" }],
            },
          ],
        },
        ["seg-1"],
        () => "第一段",
      ),
    ).toThrow("segmentAnchor");
  });

  it("相邻 segment 之间的 pauseBoundary 丢失时拒绝提交", () => {
    expect(() =>
      collectSegmentDraftChanges(
        {
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
                  type: "text",
                  text: "第二段",
                  marks: [{ type: "segmentAnchor", attrs: { segmentId: "seg-2" } }],
                },
              ],
            },
          ],
        },
        ["seg-1", "seg-2"],
        (segmentId) =>
          ({
            "seg-1": "第一段",
            "seg-2": "第二段",
          })[segmentId] ?? "",
      ),
    ).toThrow("pauseBoundary");
  });

  it("粘贴文本时会把换行折叠为空格，避免生成额外 paragraph", () => {
    expect(normalizeEditorPastedText("第一行\r\n第二行\n第三行")).toBe(
      "第一行 第二行 第三行",
    );
  });
});
