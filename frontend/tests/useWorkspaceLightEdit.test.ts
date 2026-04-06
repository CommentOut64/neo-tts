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
});
