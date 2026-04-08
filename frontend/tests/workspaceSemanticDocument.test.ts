import { describe, expect, it } from "vitest";

import { buildWorkspaceSemanticDocument } from "../src/components/workspace/workspace-editor/buildWorkspaceSemanticDocument";

describe("workspace semantic document", () => {
  it("source_text 可顺序对齐时会产出 sourceBlocks", () => {
    const semanticDocument = buildWorkspaceSemanticDocument({
      sourceText: "第一句。第二句。\n第三句。",
      segments: [
        {
          segmentId: "seg-1",
          orderKey: 1,
          text: "第一句。",
          renderStatus: "completed",
        },
        {
          segmentId: "seg-2",
          orderKey: 2,
          text: "第二句。",
          renderStatus: "completed",
        },
        {
          segmentId: "seg-3",
          orderKey: 3,
          text: "第三句。",
          renderStatus: "completed",
        },
      ],
      edges: [
        {
          edgeId: "edge-1",
          leftSegmentId: "seg-1",
          rightSegmentId: "seg-2",
          pauseDurationSeconds: 0.3,
          boundaryStrategy: "crossfade",
        },
        {
          edgeId: "edge-2",
          leftSegmentId: "seg-2",
          rightSegmentId: "seg-3",
          pauseDurationSeconds: 0.5,
          boundaryStrategy: "crossfade",
        },
      ],
      dirtySegmentIds: new Set(["seg-2"]),
    });

    expect(semanticDocument.segmentOrder).toEqual(["seg-1", "seg-2", "seg-3"]);
    expect(semanticDocument.segmentsById["seg-2"].isDirty).toBe(true);
    expect(semanticDocument.sourceBlocks).toEqual([
      {
        blockId: "block-1",
        rawLineText: "第一句。第二句。",
        segmentIds: ["seg-1", "seg-2"],
      },
      {
        blockId: "block-2",
        rawLineText: "第三句。",
        segmentIds: ["seg-3"],
      },
    ]);
    expect(semanticDocument.compositionAvailability).toEqual({
      ready: true,
      reason: null,
    });
  });

  it("source_text 缺失时组合式不可用", () => {
    const semanticDocument = buildWorkspaceSemanticDocument({
      sourceText: null,
      segments: [
        {
          segmentId: "seg-1",
          orderKey: 1,
          text: "第一句。",
          renderStatus: "completed",
        },
      ],
      edges: [],
    });

    expect(semanticDocument.sourceBlocks).toEqual([]);
    expect(semanticDocument.compositionAvailability).toEqual({
      ready: false,
      reason: "missing_source_text",
    });
  });

  it("source_text 对齐失败时组合式不可用", () => {
    const semanticDocument = buildWorkspaceSemanticDocument({
      sourceText: "第一句。\n第三句。",
      segments: [
        {
          segmentId: "seg-1",
          orderKey: 1,
          text: "第一句。",
          renderStatus: "completed",
        },
        {
          segmentId: "seg-2",
          orderKey: 2,
          text: "第二句。",
          renderStatus: "completed",
        },
      ],
      edges: [],
    });

    expect(semanticDocument.sourceBlocks).toEqual([]);
    expect(semanticDocument.compositionAvailability).toEqual({
      ready: false,
      reason: "source_text_mismatch",
    });
  });

  it("渐进态 segment 也能建立语义层", () => {
    const semanticDocument = buildWorkspaceSemanticDocument({
      sourceText: "第一句。第二句。",
      segments: [
        {
          segmentId: "seg-1",
          orderKey: 1,
          text: "第一句。",
          renderStatus: "completed",
        },
        {
          segmentId: "seg-2",
          orderKey: 2,
          text: "第二句。",
          renderStatus: "pending",
        },
      ],
      edges: [],
    });

    expect(semanticDocument.segmentOrder).toEqual(["seg-1", "seg-2"]);
    expect(semanticDocument.segmentsById["seg-2"].renderStatus).toBe("pending");
    expect(semanticDocument.compositionAvailability.ready).toBe(true);
  });
});
