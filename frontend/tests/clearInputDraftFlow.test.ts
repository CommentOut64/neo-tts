import { describe, expect, it, vi } from "vitest";

import { runClearInputDraftFlow } from "../src/components/text-input/clearInputDraftFlow";

describe("clearInputDraftFlow", () => {
  it("确认后会执行统一清空动作", async () => {
    const executeClear = vi.fn().mockResolvedValue(undefined);

    const result = await runClearInputDraftFlow({
      confirmClearDraft: vi.fn().mockResolvedValue(undefined),
      executeClear,
    });

    expect(result).toBe("cleared_all");
    expect(executeClear).toHaveBeenCalledTimes(1);
  });

  it("用户取消确认时不会执行清空动作", async () => {
    const executeClear = vi.fn();

    const result = await runClearInputDraftFlow({
      confirmClearDraft: vi.fn().mockRejectedValue(new Error("cancelled")),
      executeClear,
    });

    expect(result).toBe("cancelled");
    expect(executeClear).not.toHaveBeenCalled();
  });

  it("统一清空失败时会把错误继续抛出", async () => {
    const executeClear = vi.fn().mockRejectedValue(new Error("delete failed"));

    await expect(
      runClearInputDraftFlow({
        confirmClearDraft: vi.fn().mockResolvedValue(undefined),
        executeClear,
      }),
    ).rejects.toThrow("delete failed");
    expect(executeClear).toHaveBeenCalledTimes(1);
  });
});
