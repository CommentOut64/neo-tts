import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { buildListLayoutDocument } from "../src/components/workspace/workspace-editor/buildListLayoutDocument";
import type { WorkspaceSemanticDocument } from "../src/components/workspace/workspace-editor/layoutTypes";

function resolveFromTests(relativePath: string) {
  return resolve(dirname(fileURLToPath(import.meta.url)), relativePath);
}

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
        rawLineText: "第一段。",
        segmentIds: ["seg-1"],
      },
      {
        blockId: "block-2",
        rawLineText: "第二段。",
        segmentIds: ["seg-2"],
      },
      {
        blockId: "block-3",
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

describe("workspace editor list segmentBlock refactor boundary", () => {
  it("列表式 builder 必须输出 segmentBlock 根节点，并保持 segmentId 顺序", () => {
    const plan = buildListLayoutDocument(createSemanticDocument());

    expect(plan.layoutMode).toBe("list");
    expect(plan.doc.content?.map((node) => node.type)).toEqual([
      "segmentBlock",
      "segmentBlock",
      "segmentBlock",
    ]);
    expect(plan.doc.content?.map((node) => node.attrs?.segmentId)).toEqual([
      "seg-1",
      "seg-2",
      "seg-3",
    ]);
    expect(plan.doc.content?.[0]?.content?.at(-1)?.type).toBe("pauseBoundary");
    expect(plan.doc.content?.[1]?.content?.at(-1)?.type).toBe("pauseBoundary");
    expect(plan.doc.content?.[2]?.content?.at(-1)?.type).toBe("text");
  });

  it("列表式基础结构必须落在 segmentBlock NodeView，而不是旧 widget / renderMap 路径", () => {
    const segmentBlockPath = resolveFromTests(
      "../src/components/workspace/workspace-editor/list/segmentBlock.ts",
    );
    const nodeViewPath = resolveFromTests(
      "../src/components/workspace/workspace-editor/list/SegmentBlockNodeView.vue",
    );
    const extensionSource = readFileSync(
      resolveFromTests(
        "../src/components/workspace/workspace-editor/buildEditorExtensions.ts",
      ),
      "utf8",
    );
    const normalizerSource = readFileSync(
      resolveFromTests(
        "../src/components/workspace/workspace-editor/sourceDocNormalizer.ts",
      ),
      "utf8",
    );

    expect(existsSync(segmentBlockPath)).toBe(true);
    expect(existsSync(nodeViewPath)).toBe(true);
    expect(extensionSource).toContain("segmentBlock");
    expect(extensionSource).not.toContain("ListReorderHandleDecoration");
    expect(normalizerSource).toContain("normalizeListViewDocToSourceDoc");
  });

  it("segmentBlock 必须是 isolating block，避免删空段时被相邻行合并", () => {
    const segmentBlockSource = readFileSync(
      resolveFromTests(
        "../src/components/workspace/workspace-editor/list/segmentBlock.ts",
      ),
      "utf8",
    );

    expect(segmentBlockSource).toContain("isolating: true");
  });
});
