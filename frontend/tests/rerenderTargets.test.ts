import { describe, expect, it } from "vitest";

import { resolveRerenderTargets } from "../src/components/workspace/rerenderTargets";

describe("resolveRerenderTargets", () => {
  it("会合并文本草稿段与参数待重推理段，并按时间线顺序去重", () => {
    const result = resolveRerenderTargets({
      dirtyTextSegmentIds: new Set(["seg-3", "seg-1"]),
      segments: [
        {
          segment_id: "seg-1",
          order_key: 1,
          render_status: "ready",
        },
        {
          segment_id: "seg-2",
          order_key: 2,
          render_status: "pending",
        },
        {
          segment_id: "seg-3",
          order_key: 3,
          render_status: "failed",
        },
      ],
    });

    expect(result.segmentIds).toEqual(["seg-1", "seg-2", "seg-3"]);
    expect(result.count).toBe(3);
  });

  it("只要段状态不是 ready，就应计入待重推理集合", () => {
    const result = resolveRerenderTargets({
      dirtyTextSegmentIds: new Set(),
      segments: [
        {
          segment_id: "seg-1",
          order_key: 1,
          render_status: "ready",
        },
        {
          segment_id: "seg-2",
          order_key: 2,
          render_status: "pending",
        },
      ],
    });

    expect(result.segmentIds).toEqual(["seg-2"]);
    expect(result.count).toBe(1);
  });
});
