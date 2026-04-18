import { beforeEach, describe, expect, it } from "vitest";
import { nextTick } from "vue";

import { useWorkspaceLightEdit } from "../src/composables/useWorkspaceLightEdit";

describe("useWorkspaceLightEdit", () => {
  const lightEdit = useWorkspaceLightEdit();

  beforeEach(async () => {
    lightEdit.clearAll();
    await nextTick();
  });

  it("clearAll 会同步清空脏段计数和草稿映射", async () => {
    lightEdit.setDraft("seg-1", "新的文本");
    lightEdit.setDraft("seg-2", "另一个文本");
    await nextTick();

    expect(lightEdit.dirtyCount.value).toBe(2);
    expect(lightEdit.getDraft("seg-1")).toBe("新的文本");

    lightEdit.clearAll();
    await nextTick();

    expect(lightEdit.dirtyCount.value).toBe(0);
    expect(Array.from(lightEdit.dirtySegmentIds.value)).toEqual([]);
    expect(lightEdit.getDraft("seg-1")).toBeUndefined();
    expect(lightEdit.getDraft("seg-2")).toBeUndefined();
  });

  it("replaceAllDrafts 会整组替换草稿并重建脏段集合", async () => {
    lightEdit.setDraft("seg-1", "旧文本");
    await nextTick();

    lightEdit.replaceAllDrafts({
      "seg-2": "新的第二段",
      "seg-3": "新的第三段",
    });
    await nextTick();

    expect(lightEdit.dirtyCount.value).toBe(2);
    expect(Array.from(lightEdit.dirtySegmentIds.value)).toEqual(["seg-2", "seg-3"]);
    expect(lightEdit.getDraft("seg-1")).toBeUndefined();
    expect(lightEdit.getDraft("seg-2")).toBe("新的第二段");
    expect(lightEdit.getDraft("seg-3")).toBe("新的第三段");
  });

  it("setDraft 当前会把整段字符串直接记为脏草稿", async () => {
    lightEdit.setDraft("seg-1", "整段 display text");
    await nextTick();

    expect(lightEdit.dirtyCount.value).toBe(1);
    expect(lightEdit.isDirty("seg-1")).toBe(true);
    expect(lightEdit.getDraft("seg-1")).toBe("整段 display text");
  });

  it("replaceAllDrafts 接受 Map<string, string> 作为当前字符串草稿模型", async () => {
    lightEdit.replaceAllDrafts(new Map([
      ["seg-9", "来自 Map 的草稿"],
    ]));
    await nextTick();

    expect(lightEdit.dirtyCount.value).toBe(1);
    expect(Array.from(lightEdit.dirtySegmentIds.value)).toEqual(["seg-9"]);
    expect(lightEdit.getDraft("seg-9")).toBe("来自 Map 的草稿");
  });
});
