import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { reactive } from "vue";
import { describe, expect, it } from "vitest";

import type { EditableEdge } from "../src/types/editSession";
import {
  buildWorkspaceDraftPersistKey,
  buildWorkspaceViewRevisionKey,
  canStartListReorder,
  cloneWorkspaceSerializable,
  collectPauseBoundaryAttrPatches,
  findCanvasTarget,
  findReorderHandleTarget,
  haveSameEdgeTopology,
  requestLayoutMode,
  resolveWorkspaceSessionItems,
  shouldShowListReorderHandles,
  shouldBlockEdgeEditing,
  shouldPreserveLocalTextDraftsOnVersionChange,
} from "../src/components/workspace/workspace-editor/workspaceEditorHostModel";
import * as workspaceEditorHostModel from "../src/components/workspace/workspace-editor/workspaceEditorHostModel";
import type { WorkspaceRenderMap } from "../src/components/workspace/workspace-editor/layoutTypes";

const workspaceEditorHostSource = readFileSync(
  resolve(
    dirname(fileURLToPath(import.meta.url)),
    "../src/components/workspace/WorkspaceEditorHost.vue",
  ),
  "utf8",
);
const pauseBoundaryNodeViewSource = readFileSync(
  resolve(
    dirname(fileURLToPath(import.meta.url)),
    "../src/components/workspace/workspace-editor/PauseBoundaryNodeView.vue",
  ),
  "utf8",
);
const workspaceEditorHostModelSource = readFileSync(
  resolve(
    dirname(fileURLToPath(import.meta.url)),
    "../src/components/workspace/workspace-editor/workspaceEditorHostModel.ts",
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

  it("findReorderHandleTarget 会命中新 segmentBlock gutter handle", () => {
    const handleTarget = {
      getAttribute(name: string) {
        return name === "data-segment-id" ? "seg-2" : null;
      },
      closest(selector: string) {
        if (selector === "[data-segment-block-handle]") {
          return this;
        }
        return null;
      },
    };

    expect(findReorderHandleTarget(handleTarget as never)).toBe("seg-2");
  });

  it("只有展示态且无草稿、无待重推理、无活动作业时才允许开始重排", () => {
    expect(
      canStartListReorder({
        layoutMode: "list",
        isEditing: false,
        sessionStatus: "ready",
        hasTextDraft: false,
        hasParameterDraft: false,
        hasPendingRerender: false,
        canMutate: true,
        isInteractionLocked: false,
      }),
    ).toBe(true);

    expect(
      canStartListReorder({
        layoutMode: "list",
        isEditing: false,
        sessionStatus: "ready",
        hasTextDraft: false,
        hasParameterDraft: false,
        hasPendingRerender: true,
        canMutate: true,
        isInteractionLocked: false,
      }),
    ).toBe(false);

    expect(
      canStartListReorder({
        layoutMode: "list",
        isEditing: false,
        sessionStatus: "ready",
        hasTextDraft: false,
        hasParameterDraft: true,
        hasPendingRerender: false,
        canMutate: true,
        isInteractionLocked: false,
      }),
    ).toBe(false);
  });

  it("禁用重排时不再显示拖拽 grip，但行序号仍保留", () => {
    expect(
      shouldShowListReorderHandles({
        canStartReorder: false,
        hasReorderDraft: true,
      }),
    ).toBe(false);

    expect(
      shouldShowListReorderHandles({
        canStartReorder: false,
        hasReorderDraft: false,
      }),
    ).toBe(false);
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

  it("展示态删段遇到未提交正文草稿时必须阻止，避免版本切换冲掉本地 draft", () => {
    const result = (
      workspaceEditorHostModel as typeof workspaceEditorHostModel & {
        resolveSegmentDeletionGuard?: (input: {
          segmentCount: number;
          canMutate: boolean;
          isInteractionLocked: boolean;
          hasTextDraft: boolean;
          hasParameterDraft: boolean;
          hasPendingRerender: boolean;
          hasReorderDraft: boolean;
        }) => unknown;
      }
    ).resolveSegmentDeletionGuard?.({
      segmentCount: 3,
      canMutate: true,
      isInteractionLocked: false,
      hasTextDraft: true,
      hasParameterDraft: false,
      hasPendingRerender: false,
      hasReorderDraft: false,
    });

    expect(result).toEqual({
      allowed: false,
      reason: "请先完成或放弃当前正文草稿",
    });
  });

  it("展示态右键删段确认框会关闭 body 滚动条补偿，避免右侧留白", () => {
    expect(workspaceEditorHostSource).toContain("lockScroll: false");
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

  it("不会再把 workspace working_text 实时回写到输入页", () => {
    expect(workspaceEditorHostSource).not.toContain("syncFromWorkspaceDraft");
    expect(workspaceEditorHostSource).not.toContain("syncInputDraftToSessionText");
  });

  it("正文区顶部入口应改成结束会话，而不是继续暴露清空会话语义", () => {
    expect(workspaceEditorHostSource).toContain("结束会话");
    expect(workspaceEditorHostSource).not.toContain("清空会话");
  });

  it("停顿节点模板不再通过 align-middle 或 leading-none 做基线补偿", () => {
    expect(pauseBoundaryNodeViewSource).not.toContain("align-middle");
    expect(pauseBoundaryNodeViewSource).not.toContain("leading-none");
  });

  it("停顿节点会把 layoutMode 透传到 DOM", () => {
    expect(pauseBoundaryNodeViewSource).toContain(":data-layout-mode=");
  });

  it("宿主层固定停顿节点当前高度，并把字号恢复到 11px", () => {
    expect(workspaceEditorHostSource).toContain("[data-pause-boundary] button");
    expect(workspaceEditorHostSource).toContain(
      "font-size: 11px;",
    );
    expect(workspaceEditorHostSource).toContain(
      "line-height: normal;",
    );
    expect(workspaceEditorHostSource).toContain(
      "height: 19.62px;",
    );
    expect(workspaceEditorHostSource).toContain(
      "vertical-align: baseline;",
    );
  });

  it("宿主层不再依赖旧 widget handle 和 paragraph padding-left 维持列表式 gutter", () => {
    expect(workspaceEditorHostSource).not.toContain(
      "editor.storage.listReorderHandleDecoration.state",
    );
    expect(workspaceEditorHostSource).not.toContain("padding-left: 38px;");
    expect(workspaceEditorHostSource).toContain("segment-block-gutter");
    expect(workspaceEditorHostSource).toContain("segment-block-content");
    expect(workspaceEditorHostModelSource).toContain(
      "[data-segment-block-handle]",
    );
    expect(workspaceEditorHostModelSource).not.toContain(
      "[data-segment-handle-for]",
    );
  });

  it("编辑态可隐藏 gutter 内容，但结构列宽必须保留", () => {
    expect(workspaceEditorHostSource).toContain("segment-block-gutter");
    expect(workspaceEditorHostSource).toMatch(
      /segment-block-gutter[\s\S]*(width|min-width):/,
    );
    expect(workspaceEditorHostSource).toContain("showReorderHandle: canStartFreshReorder.value");
    expect(workspaceEditorHostSource).toMatch(
      /segment-line-editing[\s\S]*segment-reorder-line-number[\s\S]*opacity:\s*0/,
    );
  });

  it("禁用重排时只隐藏 grip，不隐藏行序号", () => {
    expect(workspaceEditorHostSource).toContain(
      '.segment-reorder-handle[data-visible="false"] .segment-reorder-grip',
    );
    expect(workspaceEditorHostSource).not.toContain(
      '.segment-reorder-handle[data-visible="false"] .segment-reorder-line-number',
    );
  });

  it("列表式左侧强调线改为装饰层绘制，避免 border-left 挤压正文布局", () => {
    expect(workspaceEditorHostSource).toMatch(
      /:deep\(\.ProseMirror \.segment-block\)::before/,
    );
    expect(workspaceEditorHostSource).toContain(
      "--segment-block-accent-width: 3px;",
    );
    expect(workspaceEditorHostSource).toContain(
      "--segment-block-accent-color: color-mix(in srgb, var(--color-accent) 58%, transparent);",
    );
    expect(workspaceEditorHostSource).not.toContain(
      "border-left: 3px solid var(--color-warning);",
    );
    expect(workspaceEditorHostSource).not.toContain("border-left-color:");
  });

});
