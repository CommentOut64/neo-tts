import { describe, expect, it, vi } from "vitest";

import { createSegmentRerenderQueue } from "../src/components/workspace/segmentRerenderQueue";

describe("segmentRerenderQueue", () => {
  it("全部目标段都成功完成后，返回可用于输入页回填的 full completion 结果", async () => {
    const refreshSession = vi.fn().mockResolvedValue(undefined);
    const clearDraft = vi.fn();
    const queue = createSegmentRerenderQueue({
      submitSegmentUpdate: vi
        .fn()
        .mockResolvedValueOnce({
          jobId: "job-1",
          waitForTerminal: vi.fn().mockResolvedValue("completed"),
          cancel: vi.fn(),
        })
        .mockResolvedValueOnce({
          jobId: "job-2",
          waitForTerminal: vi.fn().mockResolvedValue("completed"),
          cancel: vi.fn(),
        }),
      clearDraft,
      refreshSession,
    });

    const result = await queue.run(["seg-1", "seg-2"]);

    expect(result).toEqual({
      completedSegmentIds: ["seg-1", "seg-2"],
      completedAll: true,
      terminalStatus: "completed",
    });
    expect(clearDraft).toHaveBeenCalledTimes(2);
    expect(refreshSession).toHaveBeenCalledTimes(1);
  });

  it("只要出现取消或部分取消，就不会返回 full completion 结果", async () => {
    const refreshSession = vi.fn().mockResolvedValue(undefined);
    const clearDraft = vi.fn();
    const queue = createSegmentRerenderQueue({
      submitSegmentUpdate: vi
        .fn()
        .mockResolvedValueOnce({
          jobId: "job-1",
          waitForTerminal: vi.fn().mockResolvedValue("completed"),
          cancel: vi.fn(),
        })
        .mockResolvedValueOnce({
          jobId: "job-2",
          waitForTerminal: vi.fn().mockResolvedValue("cancelled_partial"),
          cancel: vi.fn(),
        }),
      clearDraft,
      refreshSession,
    });

    const result = await queue.run(["seg-1", "seg-2"]);

    expect(result).toEqual({
      completedSegmentIds: ["seg-1"],
      completedAll: false,
      terminalStatus: "cancelled_partial",
    });
    expect(clearDraft).toHaveBeenCalledTimes(1);
    expect(refreshSession).toHaveBeenCalledTimes(1);
  });
});
