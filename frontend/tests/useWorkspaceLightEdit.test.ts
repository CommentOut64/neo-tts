import { beforeEach, describe, expect, it } from "vitest";
import { nextTick } from "vue";

import { useWorkspaceLightEdit } from "../src/composables/useWorkspaceLightEdit";
import type { WorkspaceSegmentTextDraft } from "../src/components/workspace/workspace-editor/terminalRegionModel";

function createDraft(
  overrides: Partial<WorkspaceSegmentTextDraft> = {},
): WorkspaceSegmentTextDraft {
  return {
    segmentId: "seg-1",
    stem: "新的文本",
    terminal_raw: "",
    terminal_closer_suffix: "",
    terminal_source: "synthetic",
    ...overrides,
  };
}

describe("useWorkspaceLightEdit", () => {
  const lightEdit = useWorkspaceLightEdit();

  beforeEach(async () => {
    lightEdit.clearAll();
    await nextTick();
  });

  it("clearAll 会同步清空脏段计数和草稿映射", async () => {
    lightEdit.setDraft("seg-1", createDraft({ segmentId: "seg-1" }));
    lightEdit.setDraft(
      "seg-2",
      createDraft({ segmentId: "seg-2", stem: "另一个文本", terminal_raw: "？", terminal_source: "original" }),
    );
    await nextTick();

    expect(lightEdit.dirtyCount.value).toBe(2);
    expect(lightEdit.getDraft("seg-1")).toEqual(createDraft({ segmentId: "seg-1" }));

    lightEdit.clearAll();
    await nextTick();

    expect(lightEdit.dirtyCount.value).toBe(0);
    expect(Array.from(lightEdit.dirtySegmentIds.value)).toEqual([]);
    expect(lightEdit.getDraft("seg-1")).toBeUndefined();
    expect(lightEdit.getDraft("seg-2")).toBeUndefined();
  });

  it("replaceAllDrafts 会整组替换草稿并重建脏段集合", async () => {
    lightEdit.setDraft("seg-1", createDraft({ segmentId: "seg-1", stem: "旧文本" }));
    await nextTick();

    lightEdit.replaceAllDrafts({
      "seg-2": createDraft({ segmentId: "seg-2", stem: "新的第二段" }),
      "seg-3": createDraft({ segmentId: "seg-3", stem: "新的第三段" }),
    });
    await nextTick();

    expect(lightEdit.dirtyCount.value).toBe(2);
    expect(Array.from(lightEdit.dirtySegmentIds.value)).toEqual(["seg-2", "seg-3"]);
    expect(lightEdit.getDraft("seg-1")).toBeUndefined();
    expect(lightEdit.getDraft("seg-2")).toEqual(
      createDraft({ segmentId: "seg-2", stem: "新的第二段" }),
    );
    expect(lightEdit.getDraft("seg-3")).toEqual(
      createDraft({ segmentId: "seg-3", stem: "新的第三段" }),
    );
  });

  it("setDraft 会把结构化 draft 直接记为脏草稿", async () => {
    lightEdit.setDraft(
      "seg-1",
      createDraft({
        segmentId: "seg-1",
        stem: "整段正文",
        terminal_raw: "？",
        terminal_source: "original",
      }),
    );
    await nextTick();

    expect(lightEdit.dirtyCount.value).toBe(1);
    expect(lightEdit.isDirty("seg-1")).toBe(true);
    expect(lightEdit.getDraft("seg-1")).toEqual(
      createDraft({
        segmentId: "seg-1",
        stem: "整段正文",
        terminal_raw: "？",
        terminal_source: "original",
      }),
    );
  });

  it("replaceAllDrafts 接受 Map<string, WorkspaceSegmentTextDraft> 作为结构化草稿模型", async () => {
    lightEdit.replaceAllDrafts(new Map([
      ["seg-9", createDraft({ segmentId: "seg-9", stem: "来自 Map 的草稿" })],
    ]));
    await nextTick();

    expect(lightEdit.dirtyCount.value).toBe(1);
    expect(Array.from(lightEdit.dirtySegmentIds.value)).toEqual(["seg-9"]);
    expect(lightEdit.getDraft("seg-9")).toEqual(
      createDraft({ segmentId: "seg-9", stem: "来自 Map 的草稿" }),
    );
  });

  it("删空段仍保留为 dirty draft，但不应计入待重推理集合", async () => {
    lightEdit.replaceAllDrafts({
      "seg-1": createDraft({ segmentId: "seg-1", stem: "" }),
      "seg-2": createDraft({ segmentId: "seg-2", stem: "仍需重推理的正文改动" }),
    });
    await nextTick();

    expect(Array.from(lightEdit.dirtySegmentIds.value)).toEqual(["seg-1", "seg-2"]);
    expect(Array.from(lightEdit.rerenderSegmentIds.value)).toEqual(["seg-2"]);
  });
});
