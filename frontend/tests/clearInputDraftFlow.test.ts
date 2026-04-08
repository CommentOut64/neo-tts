import { describe, expect, it, vi } from "vitest";

import { runClearInputDraftFlow } from "../src/components/text-input/clearInputDraftFlow";

describe("clearInputDraftFlow", () => {
  it("没有会话内容时只清空输入稿", async () => {
    const clearDraft = vi.fn();
    const clearSession = vi.fn();

    const result = await runClearInputDraftFlow({
      confirmClearDraft: vi.fn().mockResolvedValue(undefined),
      loadHasSessionContent: vi.fn().mockResolvedValue(false),
      chooseSessionCleanup: vi.fn(),
      clearDraft,
      clearSession,
    });

    expect(result).toBe("cleared_draft");
    expect(clearDraft).toHaveBeenCalledTimes(1);
    expect(clearSession).not.toHaveBeenCalled();
  });

  it("有会话内容且用户选择同步清理时，会同时清空会话正文", async () => {
    const clearDraft = vi.fn();
    const clearSession = vi.fn().mockResolvedValue(undefined);

    const result = await runClearInputDraftFlow({
      confirmClearDraft: vi.fn().mockResolvedValue(undefined),
      loadHasSessionContent: vi.fn().mockResolvedValue(true),
      chooseSessionCleanup: vi.fn().mockResolvedValue(true),
      clearDraft,
      clearSession,
    });

    expect(result).toBe("cleared_draft_and_session");
    expect(clearSession).toHaveBeenCalledTimes(1);
    expect(clearDraft).toHaveBeenCalledTimes(1);
  });

  it("有会话内容但用户选择保留时，只清空输入稿", async () => {
    const clearDraft = vi.fn();
    const clearSession = vi.fn();

    const result = await runClearInputDraftFlow({
      confirmClearDraft: vi.fn().mockResolvedValue(undefined),
      loadHasSessionContent: vi.fn().mockResolvedValue(true),
      chooseSessionCleanup: vi.fn().mockResolvedValue(false),
      clearDraft,
      clearSession,
    });

    expect(result).toBe("cleared_draft");
    expect(clearDraft).toHaveBeenCalledTimes(1);
    expect(clearSession).not.toHaveBeenCalled();
  });

  it("同步清理会话失败时，不会提前清空输入稿", async () => {
    const clearDraft = vi.fn();

    await expect(
      runClearInputDraftFlow({
        confirmClearDraft: vi.fn().mockResolvedValue(undefined),
        loadHasSessionContent: vi.fn().mockResolvedValue(true),
        chooseSessionCleanup: vi.fn().mockResolvedValue(true),
        clearDraft,
        clearSession: vi.fn().mockRejectedValue(new Error("delete failed")),
      }),
    ).rejects.toThrow("delete failed");

    expect(clearDraft).not.toHaveBeenCalled();
  });
});
