import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import * as segmentDeletion from "../src/components/workspace/segmentDeletion";
import type { WorkspaceSegmentTextDraft } from "../src/components/workspace/workspace-editor/terminalRegionModel";

const segmentDeletionSource = readFileSync(
  resolve(
    dirname(fileURLToPath(import.meta.url)),
    "../src/components/workspace/segmentDeletion.ts",
  ),
  "utf8",
);

function createDraft(
  overrides: Partial<WorkspaceSegmentTextDraft> = {},
): WorkspaceSegmentTextDraft {
  return {
    segmentId: "seg-1",
    stem: "",
    terminal_raw: "",
    terminal_closer_suffix: "",
    terminal_source: "original",
    ...overrides,
  };
}

describe("segment deletion helpers", () => {
  it("编辑态删段检测会按结构化 stem 判定删段候选", () => {
    expect(
      segmentDeletion.detectDeletionCandidates(
        {
          type: "doc",
          content: [
            {
              type: "segmentBlock",
              attrs: { segmentId: "seg-1" },
              content: [
                { type: "text", text: "保留第一段" },
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
                  text: "。",
                  marks: [{ type: "terminalCapsule", attrs: { segmentId: "seg-2" } }],
                },
                {
                  type: "pauseBoundary",
                  attrs: {
                    edgeId: "edge-2",
                    leftSegmentId: "seg-2",
                    rightSegmentId: "seg-3",
                    layoutMode: "list",
                    crossBlock: false,
                  },
                },
              ],
            },
            {
              type: "segmentBlock",
              attrs: { segmentId: "seg-3" },
              content: [],
            },
          ],
        },
        ["seg-1", "seg-2", "seg-3"],
      ),
    ).toEqual(["seg-2", "seg-3"]);
  });

  it("正文 region 里只剩标点时不再被误判为删段候选", () => {
    expect(
      segmentDeletion.detectDeletionCandidates(
        {
          type: "doc",
          content: [
            {
              type: "segmentBlock",
              attrs: { segmentId: "seg-1" },
              content: [{ type: "text", text: "!?" }],
            },
          ],
        },
        ["seg-1"],
      ),
    ).toEqual([]);
  });

  it("整段 block 被删掉时，仍会把缺失段识别为删段候选", () => {
    expect(
      segmentDeletion.detectDeletionCandidates(
        {
          type: "doc",
          content: [
            {
              type: "segmentBlock",
              attrs: { segmentId: "seg-1" },
              content: [{ type: "text", text: "保留第一段" }],
            },
            {
              type: "segmentBlock",
              attrs: { segmentId: "seg-3" },
              content: [{ type: "text", text: "保留第三段" }],
            },
          ],
        },
        ["seg-1", "seg-2", "seg-3"],
      ),
    ).toEqual(["seg-2"]);
  });

  it("取消删段后会按结构化 draft 回填 stem 与 terminal region，并保留 pauseBoundary", () => {
    expect(
      segmentDeletion.patchEditorDocForRestoredSegments(
        {
          type: "doc",
          content: [
            {
              type: "segmentBlock",
              attrs: { segmentId: "seg-1" },
              content: [
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
              content: [{ type: "text", text: "保留第二段" }],
            },
          ],
        },
        ["seg-1", "seg-2"],
        [{
          segmentId: "seg-1",
          originalDraft: createDraft({
            segmentId: "seg-1",
            stem: "恢复后的第一段",
            terminal_raw: "？",
            terminal_closer_suffix: "」",
            terminal_source: "original",
          }),
        }],
      ),
    ).toEqual({
      type: "doc",
      content: [
        {
          type: "segmentBlock",
          attrs: { segmentId: "seg-1" },
          content: [
            {
              type: "text",
              text: "恢复后的第一段",
              marks: [{ type: "segmentAnchor", attrs: { segmentId: "seg-1" } }],
            },
            {
              type: "text",
              text: "？」",
              marks: [
                { type: "segmentAnchor", attrs: { segmentId: "seg-1" } },
                { type: "terminalCapsule", attrs: { segmentId: "seg-1", terminalSource: "original" } },
              ],
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
          content: [{ type: "text", text: "保留第二段" }],
        },
      ],
    });
  });

  it("取消删段恢复 synthetic terminal 时，会按语言回填显示句号而不是丢失 terminal region", () => {
    expect(
      segmentDeletion.patchEditorDocForRestoredSegments(
        {
          type: "doc",
          content: [
            {
              type: "segmentBlock",
              attrs: { segmentId: "seg-en" },
              content: [
                {
                  type: "pauseBoundary",
                  attrs: {
                    edgeId: "edge-en",
                    leftSegmentId: "seg-en",
                    rightSegmentId: "seg-2",
                    layoutMode: "list",
                    crossBlock: false,
                  },
                },
              ],
            },
          ],
        },
        ["seg-en"],
        [{
          segmentId: "seg-en",
          originalDraft: createDraft({
            segmentId: "seg-en",
            stem: "Hello world",
            terminal_raw: "",
            terminal_closer_suffix: "",
            terminal_source: "synthetic",
          }),
          detectedLanguage: "en",
          textLanguage: "en",
        }],
      ),
    ).toEqual({
      type: "doc",
      content: [
        {
          type: "segmentBlock",
          attrs: { segmentId: "seg-en" },
          content: [
            {
              type: "text",
              text: "Hello world",
              marks: [{ type: "segmentAnchor", attrs: { segmentId: "seg-en" } }],
            },
            {
              type: "text",
              text: ".",
              marks: [
                { type: "segmentAnchor", attrs: { segmentId: "seg-en" } },
                { type: "terminalCapsule", attrs: { segmentId: "seg-en", terminalSource: "synthetic" } },
              ],
            },
            {
              type: "pauseBoundary",
              attrs: {
                edgeId: "edge-en",
                leftSegmentId: "seg-en",
                rightSegmentId: "seg-2",
                layoutMode: "list",
                crossBlock: false,
              },
            },
          ],
        },
      ],
    });
  });

  it("取消删段时若整段 block 已消失，会按原顺序重建该段并带回 pauseBoundary", () => {
    expect(
      segmentDeletion.patchEditorDocForRestoredSegments(
        {
          type: "doc",
          content: [
            {
              type: "segmentBlock",
              attrs: { segmentId: "seg-1" },
              content: [
                { type: "text", text: "保留第一段" },
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
              attrs: { segmentId: "seg-3" },
              content: [{ type: "text", text: "保留第三段" }],
            },
          ],
        },
        ["seg-1", "seg-2", "seg-3"],
        [{
          segmentId: "seg-2",
          originalDraft: createDraft({
            segmentId: "seg-2",
            stem: "恢复后的第二段",
            terminal_raw: "。",
            terminal_closer_suffix: "",
            terminal_source: "original",
          }),
          trailingEdge: {
            edgeId: "edge-2",
            leftSegmentId: "seg-2",
            rightSegmentId: "seg-3",
            pauseDurationSeconds: 0.4,
            boundaryStrategy: "crossfade",
          },
        }],
      ),
    ).toEqual({
      type: "doc",
      content: [
        {
          type: "segmentBlock",
          attrs: { segmentId: "seg-1" },
          content: [
            { type: "text", text: "保留第一段" },
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
              text: "恢复后的第二段",
              marks: [{ type: "segmentAnchor", attrs: { segmentId: "seg-2" } }],
            },
            {
              type: "text",
              text: "。",
              marks: [
                { type: "segmentAnchor", attrs: { segmentId: "seg-2" } },
                { type: "terminalCapsule", attrs: { segmentId: "seg-2", terminalSource: "original" } },
              ],
            },
            {
              type: "pauseBoundary",
              attrs: {
                edgeId: "edge-2",
                leftSegmentId: "seg-2",
                rightSegmentId: "seg-3",
                pauseDurationSeconds: 0.4,
                boundaryStrategy: "crossfade",
                layoutMode: "list",
                crossBlock: false,
              },
            },
          ],
        },
        {
          type: "segmentBlock",
          attrs: { segmentId: "seg-3" },
          content: [{ type: "text", text: "保留第三段" }],
        },
      ],
    });
  });

  it("批量删段时一旦中途失败，只返回已成功删除的段和失败位置", async () => {
    const runDeletionJobs = (
      segmentDeletion as typeof segmentDeletion & {
        runDeletionJobs?: (input: {
          segmentIds: string[];
          deleteSegment: (segmentId: string) => Promise<void>;
        }) => Promise<unknown>;
      }
    ).runDeletionJobs;

    const result = await runDeletionJobs?.({
      segmentIds: ["seg-1", "seg-2", "seg-3"],
      deleteSegment: async (segmentId) => {
        if (segmentId === "seg-2") {
          throw new Error("delete_failed");
        }
      },
    });

    expect(result).toEqual({
      deletedSegmentIds: ["seg-1"],
      failedSegmentId: "seg-2",
      completed: false,
    });
  });

  it("编辑态删段确认框会关闭 body 滚动条补偿，避免右侧留白", () => {
    expect(segmentDeletionSource).toContain("lockScroll: false");
  });
});
