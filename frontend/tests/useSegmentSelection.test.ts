import { beforeEach, describe, expect, it } from "vitest";
import { nextTick } from "vue";

import { useSegmentSelection } from "../src/composables/useSegmentSelection";

describe("useSegmentSelection", () => {
  const selection = useSegmentSelection();

  beforeEach(async () => {
    selection.clearSelection();
    await nextTick();
  });

  it("select 会让 selectedSegmentIds 对外响应更新", async () => {
    selection.select("seg-1");
    await nextTick();

    expect(Array.from(selection.selectedSegmentIds.value)).toEqual(["seg-1"]);
    expect(selection.primarySelectedSegmentId.value).toBe("seg-1");
  });

  it("rangeSelect 会按给定顺序替换为连续区间", async () => {
    selection.select("seg-2");
    await nextTick();

    selection.rangeSelect("seg-4", ["seg-1", "seg-2", "seg-3", "seg-4"]);
    await nextTick();

    expect(Array.from(selection.selectedSegmentIds.value)).toEqual([
      "seg-2",
      "seg-3",
      "seg-4",
    ]);
  });

  it("selectEdge 会清空段选择并切到 edge 选择", async () => {
    selection.select("seg-1");
    await nextTick();

    selection.selectEdge("edge-1");
    await nextTick();

    expect(Array.from(selection.selectedSegmentIds.value)).toEqual([]);
    expect(selection.primarySelectedSegmentId.value).toBeNull();
    expect(selection.selectedEdgeId.value).toBe("edge-1");
    expect(selection.isEdgeSelected("edge-1")).toBe(true);
  });

  it("restoreSelection 会恢复段与 edge 的选择快照", async () => {
    selection.select("seg-3");
    await nextTick();
    const snapshot = selection.captureSelection();

    selection.selectEdge("edge-2");
    await nextTick();
    selection.restoreSelection(snapshot);
    await nextTick();

    expect(Array.from(selection.selectedSegmentIds.value)).toEqual(["seg-3"]);
    expect(selection.primarySelectedSegmentId.value).toBe("seg-3");
    expect(selection.selectedEdgeId.value).toBeNull();
  });
});
