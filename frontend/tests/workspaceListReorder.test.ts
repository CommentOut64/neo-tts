import { describe, expect, it } from "vitest";

import { buildNextSegmentOrder } from "../src/components/workspace/workspace-editor/buildNextSegmentOrder";
import { computeListDropIntent } from "../src/components/workspace/workspace-editor/computeListDropIntent";

describe("workspace list reorder helpers", () => {
  it("computeListDropIntent 在目标主体区域返回 swap", () => {
    expect(
      computeListDropIntent({
        clientY: 120,
        rect: { top: 100, bottom: 160, height: 60 },
        draggingSegmentId: "seg-1",
        targetSegmentId: "seg-2",
      }),
    ).toBe("swap");
  });

  it("computeListDropIntent 在目标顶部边缘返回 insert-before", () => {
    expect(
      computeListDropIntent({
        clientY: 103,
        rect: { top: 100, bottom: 160, height: 60 },
        draggingSegmentId: "seg-1",
        targetSegmentId: "seg-2",
      }),
    ).toBe("insert-before");
  });

  it("computeListDropIntent 在目标底部边缘返回 insert-after", () => {
    expect(
      computeListDropIntent({
        clientY: 157,
        rect: { top: 100, bottom: 160, height: 60 },
        draggingSegmentId: "seg-1",
        targetSegmentId: "seg-2",
      }),
    ).toBe("insert-after");
  });

  it("computeListDropIntent 命中自身时返回 null", () => {
    expect(
      computeListDropIntent({
        clientY: 120,
        rect: { top: 100, bottom: 160, height: 60 },
        draggingSegmentId: "seg-2",
        targetSegmentId: "seg-2",
      }),
    ).toBeNull();
  });

  it("buildNextSegmentOrder 支持 swap", () => {
    expect(
      buildNextSegmentOrder({
        currentOrder: ["seg-1", "seg-2", "seg-3"],
        draggingSegmentId: "seg-1",
        dropTargetSegmentId: "seg-3",
        dropIntent: "swap",
      }),
    ).toEqual(["seg-3", "seg-2", "seg-1"]);
  });

  it("buildNextSegmentOrder 支持 insert-before", () => {
    expect(
      buildNextSegmentOrder({
        currentOrder: ["seg-1", "seg-2", "seg-3"],
        draggingSegmentId: "seg-3",
        dropTargetSegmentId: "seg-1",
        dropIntent: "insert-before",
      }),
    ).toEqual(["seg-3", "seg-1", "seg-2"]);
  });

  it("buildNextSegmentOrder 支持 insert-after", () => {
    expect(
      buildNextSegmentOrder({
        currentOrder: ["seg-1", "seg-2", "seg-3"],
        draggingSegmentId: "seg-1",
        dropTargetSegmentId: "seg-2",
        dropIntent: "insert-after",
      }),
    ).toEqual(["seg-2", "seg-1", "seg-3"]);
  });

  it("buildNextSegmentOrder 自身命中或缺少条件时返回原顺序", () => {
    expect(
      buildNextSegmentOrder({
        currentOrder: ["seg-1", "seg-2", "seg-3"],
        draggingSegmentId: "seg-2",
        dropTargetSegmentId: "seg-2",
        dropIntent: "swap",
      }),
    ).toEqual(["seg-1", "seg-2", "seg-3"]);

    expect(
      buildNextSegmentOrder({
        currentOrder: ["seg-1", "seg-2", "seg-3"],
        draggingSegmentId: "seg-2",
        dropTargetSegmentId: null,
        dropIntent: null,
      }),
    ).toEqual(["seg-1", "seg-2", "seg-3"]);
  });
});
