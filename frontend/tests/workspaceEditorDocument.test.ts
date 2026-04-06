import { describe, expect, it } from "vitest";

import {
  buildSegmentEditorDocument,
  collectSegmentDraftChanges,
  normalizeEditorPastedText,
} from "../src/components/workspace/workspace-editor/documentModel";

describe("workspace editor document model", () => {
  it("按 segment 顺序构建 paragraph 文档", () => {
    const doc = buildSegmentEditorDocument([
      { segmentId: "seg-1", text: "第一段" },
      { segmentId: "seg-2", text: "第二段" },
    ]);

    expect(doc).toEqual({
      type: "doc",
      content: [
        { type: "paragraph", content: [{ type: "text", text: "第一段" }] },
        { type: "paragraph", content: [{ type: "text", text: "第二段" }] },
      ],
    });
  });

  it("提交编辑时会按 segment 对比后端文本收集变更", () => {
    const changes = collectSegmentDraftChanges(
      {
        type: "doc",
        content: [
          { type: "paragraph", content: [{ type: "text", text: "新的第一段" }] },
          { type: "paragraph", content: [{ type: "text", text: "第二段" }] },
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

  it("paragraph 数量和 segment 数量不一致时拒绝提交，避免错位回写", () => {
    expect(() =>
      collectSegmentDraftChanges(
        {
          type: "doc",
          content: [
            { type: "paragraph", content: [{ type: "text", text: "第一段" }] },
            { type: "paragraph", content: [{ type: "text", text: "额外段落" }] },
          ],
        },
        ["seg-1"],
        () => "第一段",
      ),
    ).toThrow("编辑器段落结构已变化");
  });

  it("粘贴文本时会把换行折叠为空格，避免生成额外 paragraph", () => {
    expect(normalizeEditorPastedText("第一行\r\n第二行\n第三行")).toBe(
      "第一行 第二行 第三行",
    );
  });
});
