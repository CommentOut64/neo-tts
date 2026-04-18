import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import * as segmentDeletion from "../src/components/workspace/segmentDeletion";

const segmentDeletionSource = readFileSync(
  resolve(
    dirname(fileURLToPath(import.meta.url)),
    "../src/components/workspace/segmentDeletion.ts",
  ),
  "utf8",
);

describe("segment deletion helpers", () => {
  it("编辑态删段检测会按列表式 segmentBlock 结构识别空段和仅标点段", () => {
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
                { type: "text", text: "。" },
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

  it("ASCII 句末标点当前也会被当作删段候选", () => {
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
    ).toEqual(["seg-1"]);
  });

  it("取消删段后会把文本回填到 segmentBlock，并保留 pauseBoundary", () => {
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
        [{ segmentId: "seg-1", originalText: "恢复后的第一段" }],
      ),
    ).toEqual({
      type: "doc",
      content: [
        {
          type: "segmentBlock",
          attrs: { segmentId: "seg-1" },
          content: [
            { type: "text", text: "恢复后的第一段" },
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
