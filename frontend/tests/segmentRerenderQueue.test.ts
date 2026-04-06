import { describe, expect, it, vi } from "vitest";

import {
  createSegmentRerenderQueue,
  type SegmentRerenderJobHandle,
} from "../src/components/workspace/segmentRerenderQueue";

describe("createSegmentRerenderQueue", () => {
  it("串行完成全部脏段后只刷新一次并清理锁定段", async () => {
    const clearDraft = vi.fn();
    const refreshSession = vi.fn(async () => {});
    const setLockedSegments = vi.fn();
    const submitSegmentUpdate = vi
      .fn<[string, string], Promise<SegmentRerenderJobHandle>>()
      .mockImplementation(async (segmentId) => ({
        jobId: `${segmentId}-job`,
        waitForTerminal: async () => "completed",
        cancel: async () => {},
      }));

    const queue = createSegmentRerenderQueue({
      getDraftText: (segmentId) =>
        ({
          "seg-1": "第一段",
          "seg-2": "第二段",
        })[segmentId],
      submitSegmentUpdate,
      clearDraft,
      refreshSession,
      setLockedSegments,
    });

    await queue.run(["seg-1", "seg-2"]);

    expect(submitSegmentUpdate).toHaveBeenNthCalledWith(1, "seg-1", "第一段");
    expect(submitSegmentUpdate).toHaveBeenNthCalledWith(2, "seg-2", "第二段");
    expect(clearDraft).toHaveBeenCalledTimes(2);
    expect(clearDraft).toHaveBeenCalledWith("seg-1");
    expect(clearDraft).toHaveBeenCalledWith("seg-2");
    expect(refreshSession).toHaveBeenCalledTimes(1);
    expect(setLockedSegments).toHaveBeenCalledWith(["seg-1"]);
    expect(setLockedSegments).toHaveBeenCalledWith(["seg-2"]);
    expect(setLockedSegments).toHaveBeenLastCalledWith([]);
    expect(queue.isProcessing.value).toBe(false);
    expect(queue.isCancelling.value).toBe(false);
  });

  it("取消当前 job 后会停止队列，并保留未完成段为脏态", async () => {
    const clearDraft = vi.fn();
    const refreshSession = vi.fn(async () => {});
    const setLockedSegments = vi.fn();

    let resolveFirstJob: ((status: "completed" | "failed" | "paused" | "cancelled_partial") => void) | null = null;
    const cancel = vi.fn(async () => {
      resolveFirstJob?.("cancelled_partial");
    });

    const submitSegmentUpdate = vi
      .fn<[string, string], Promise<SegmentRerenderJobHandle>>()
      .mockImplementationOnce(async () => ({
        jobId: "job-1",
        waitForTerminal: () =>
          new Promise((resolve) => {
            resolveFirstJob = resolve;
          }),
        cancel,
      }))
      .mockImplementationOnce(async () => ({
        jobId: "job-2",
        waitForTerminal: async () => "completed",
        cancel: async () => {},
      }));

    const queue = createSegmentRerenderQueue({
      getDraftText: (segmentId) =>
        ({
          "seg-1": "第一段",
          "seg-2": "第二段",
        })[segmentId],
      submitSegmentUpdate,
      clearDraft,
      refreshSession,
      setLockedSegments,
    });

    const runPromise = queue.run(["seg-1", "seg-2"]);
    await Promise.resolve();
    await queue.requestCancel();
    await runPromise;

    expect(cancel).toHaveBeenCalledTimes(1);
    expect(submitSegmentUpdate).toHaveBeenCalledTimes(1);
    expect(clearDraft).not.toHaveBeenCalled();
    expect(refreshSession).not.toHaveBeenCalled();
    expect(setLockedSegments).toHaveBeenLastCalledWith([]);
    expect(queue.isProcessing.value).toBe(false);
    expect(queue.isCancelling.value).toBe(false);
  });
});
