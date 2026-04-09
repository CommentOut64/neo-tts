import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { reactive } from "vue";
import { describe, expect, it } from "vitest";

import type { EditableEdge } from "../src/types/editSession";
import {
  buildWorkspaceDraftPersistKey,
  buildWorkspaceViewRevisionKey,
  cloneWorkspaceSerializable,
  collectPauseBoundaryAttrPatches,
  findCanvasTarget,
  haveSameEdgeTopology,
  requestLayoutMode,
  resolveWorkspaceSessionItems,
  shouldBlockEdgeEditing,
  shouldPreserveLocalTextDraftsOnVersionChange,
} from "../src/components/workspace/workspace-editor/workspaceEditorHostModel";
import type { WorkspaceRenderMap } from "../src/components/workspace/workspace-editor/layoutTypes";

const workspaceEditorHostSource = readFileSync(
  resolve(
    dirname(fileURLToPath(import.meta.url)),
    "../src/components/workspace/WorkspaceEditorHost.vue",
  ),
  "utf8",
);

function createEdge(
  edgeId: string,
  leftSegmentId: string,
  rightSegmentId: string,
  pauseDurationSeconds: number,
  boundaryStrategy = "crossfade",
): EditableEdge {
  return {
    edge_id: edgeId,
    document_id: "doc-1",
    left_segment_id: leftSegmentId,
    right_segment_id: rightSegmentId,
    pause_duration_seconds: pauseDurationSeconds,
    boundary_strategy: boundaryStrategy,
    effective_boundary_strategy: boundaryStrategy,
    pause_sample_count: null,
    boundary_sample_count: null,
    edge_status: "ready",
    edge_version: 1,
  };
}

describe("workspace editor host layout mode helpers", () => {
  it("编辑态请求切布局时保留当前模式并返回提示", () => {
    expect(
      requestLayoutMode({
        isEditing: true,
        currentMode: "composition",
        nextMode: "list",
      }),
    ).toEqual({
      layoutMode: "composition",
      warning: "请先完成或放弃当前编辑，再切换布局",
    });
  });

  it("会用 revision 号拼出当前视图 key，避免高频深序列化签名", () => {
    expect(
      buildWorkspaceViewRevisionKey({
        layoutMode: "composition",
        sourceDocRevision: 7,
        edgeTopologyRevision: 3,
        layoutHintRevision: 5,
      }),
    ).toBe("composition:7:3:5");
  });

  it("会用文档版本、模式和 revision 拼出草稿持久化 key", () => {
    expect(
      buildWorkspaceDraftPersistKey({
        documentVersion: 12,
        mode: "preview",
        sourceDocRevision: 9,
        layoutHintRevision: 4,
      }),
    ).toBe("12:preview:9:4");
  });

  it("文档版本已切换时优先使用 snapshot 当前版本数据，避免旧 segments 回灌到 Editor", () => {
    expect(
      resolveWorkspaceSessionItems({
        snapshotDocumentVersion: 5,
        currentDocumentVersion: 5,
        snapshotItems: [{ raw_text: "新文本" }],
        liveItems: [{ raw_text: "旧文本" }],
      }),
    ).toEqual([{ raw_text: "新文本" }]);
  });

  it("snapshot 版本不匹配时回退到 live 数据，避免误用旧快照", () => {
    expect(
      resolveWorkspaceSessionItems({
        snapshotDocumentVersion: 4,
        currentDocumentVersion: 5,
        snapshotItems: [{ raw_text: "旧快照文本" }],
        liveItems: [{ raw_text: "当前文本" }],
      }),
    ).toEqual([{ raw_text: "当前文本" }]);
  });

  it("能安全克隆响应式工作区状态，避免进入编辑态时抛 DataCloneError", () => {
    const sourceDoc = reactive({
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [{ type: "text", text: "第一段。" }],
        },
      ],
    });

    const cloned = cloneWorkspaceSerializable(sourceDoc);

    expect(cloned).toEqual(sourceDoc);
    expect(cloned).not.toBe(sourceDoc);
    expect(cloned.content).not.toBe(sourceDoc.content);
  });

  it("findCanvasTarget 会优先命中 edge，再回退到 segment", () => {
    const edgeTarget = {
      getAttribute(name: string) {
        return name === "data-edge-id" ? "edge-1" : null;
      },
      closest(selector: string) {
        if (selector === "[data-edge-id]") {
          return this;
        }
        return null;
      },
    };

    const segmentTarget = {
      getAttribute(name: string) {
        return name === "data-segment-id" ? "seg-1" : null;
      },
      closest(selector: string) {
        if (selector === "[data-segment-id]") {
          return this;
        }
        return null;
      },
    };

    expect(findCanvasTarget(edgeTarget as never)).toEqual({
      type: "edge",
      edgeId: "edge-1",
    });
    expect(findCanvasTarget(segmentTarget as never)).toEqual({
      type: "segment",
      segmentId: "seg-1",
    });
  });

  it("haveSameEdgeTopology 只看拓扑，不把纯 attrs 变化当成重建", () => {
    const previousEdges = [createEdge("edge-1", "seg-1", "seg-2", 0.3)];
    const nextEdges = [createEdge("edge-1", "seg-1", "seg-2", 0.8)];

    expect(haveSameEdgeTopology(nextEdges, previousEdges)).toBe(true);
    expect(
      haveSameEdgeTopology(
        [createEdge("edge-2", "seg-1", "seg-3", 0.8)],
        previousEdges,
      ),
    ).toBe(false);
  });

  it("collectPauseBoundaryAttrPatches 在纯 edge attrs 变化时只生成节点 patch 计划", () => {
    const doc = {
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
                layoutMode: "list",
                crossBlock: false,
              },
            },
          ],
        },
      ],
    } as const;

    const renderMap: WorkspaceRenderMap = {
      orderedSegmentIds: ["seg-1", "seg-2"],
      segmentRanges: [],
      segmentBlockRanges: [],
      edgeAnchors: [
        {
          edgeId: "edge-1",
          leftSegmentId: "seg-1",
          rightSegmentId: "seg-2",
          from: 5,
          to: 6,
          layoutMode: "list",
          crossBlock: false,
        },
      ],
    };

    expect(
      collectPauseBoundaryAttrPatches({
        doc,
        renderMap,
        edges: [createEdge("edge-1", "seg-1", "seg-2", 0.8, "hold")],
      }),
    ).toEqual([
      {
        from: 5,
        attrs: {
          edgeId: "edge-1",
          leftSegmentId: "seg-1",
          rightSegmentId: "seg-2",
          pauseDurationSeconds: 0.8,
          boundaryStrategy: "hold",
          layoutMode: "list",
          crossBlock: false,
        },
      },
    ]);
  });

  it("当停顿的右侧段是脏段时，禁止进入停顿设置", () => {
    expect(
      shouldBlockEdgeEditing({
        edgeId: "edge-1",
        edges: [createEdge("edge-1", "seg-1", "seg-2", 0.3)],
        dirtySegmentIds: new Set(["seg-2"]),
      }),
    ).toBe(true);

    expect(
      shouldBlockEdgeEditing({
        edgeId: "edge-1",
        edges: [createEdge("edge-1", "seg-1", "seg-2", 0.3)],
        dirtySegmentIds: new Set(["seg-1"]),
      }),
    ).toBe(false);
  });

  it("纯 edge 参数导致的安全版本切换会保留本地文本草稿", () => {
    expect(
      shouldPreserveLocalTextDraftsOnVersionChange({
        previousSessionKey: "doc-1::1::seg-1|seg-2",
        nextSessionKey: "doc-1::2::seg-1|seg-2",
        isEditing: false,
        dirtySegmentIds: new Set(["seg-2"]),
        previousSegments: [
          { segment_id: "seg-1", order_key: 1, raw_text: "第一句。" },
          { segment_id: "seg-2", order_key: 2, raw_text: "第二句。" },
        ],
        nextSegments: [
          { segment_id: "seg-1", order_key: 1, raw_text: "第一句。" },
          { segment_id: "seg-2", order_key: 2, raw_text: "第二句。" },
        ],
        previousEdges: [createEdge("edge-1", "seg-1", "seg-2", 0.3)],
        nextEdges: [createEdge("edge-1", "seg-1", "seg-2", 0.8)],
      }),
    ).toBe(true);
  });

  it("只要后端文本或 edge 拓扑发生变化，就不能沿用旧草稿", () => {
    expect(
      shouldPreserveLocalTextDraftsOnVersionChange({
        previousSessionKey: "doc-1::1::seg-1|seg-2",
        nextSessionKey: "doc-1::2::seg-1|seg-2",
        isEditing: false,
        dirtySegmentIds: new Set(["seg-2"]),
        previousSegments: [
          { segment_id: "seg-1", order_key: 1, raw_text: "第一句。" },
          { segment_id: "seg-2", order_key: 2, raw_text: "第二句。" },
        ],
        nextSegments: [
          { segment_id: "seg-1", order_key: 1, raw_text: "第一句。" },
          { segment_id: "seg-2", order_key: 2, raw_text: "第二句（后端已变）" },
        ],
        previousEdges: [createEdge("edge-1", "seg-1", "seg-2", 0.3)],
        nextEdges: [createEdge("edge-1", "seg-1", "seg-3", 0.8)],
      }),
    ).toBe(false);
  });

  it("会话正文默认以列表式打开", () => {
    expect(workspaceEditorHostSource).toContain(
      'const layoutMode = ref<WorkspaceEditorLayoutMode>("list");',
    );
  });

  it("布局切换按钮顺序应为列表式在前，组合式在后", () => {
    const listButtonIndex = workspaceEditorHostSource.indexOf(
      '@click="requestNextLayoutMode(\'list\')"',
    );
    const compositionButtonIndex = workspaceEditorHostSource.indexOf(
      '@click="requestNextLayoutMode(\'composition\')"',
    );

    expect(listButtonIndex).toBeGreaterThan(-1);
    expect(compositionButtonIndex).toBeGreaterThan(-1);
    expect(listButtonIndex).toBeLessThan(compositionButtonIndex);
  });

  it("不再提供转到文本输入页继续编辑按钮", () => {
    expect(workspaceEditorHostSource).not.toContain("转到文本输入页继续编辑");
  });
});
