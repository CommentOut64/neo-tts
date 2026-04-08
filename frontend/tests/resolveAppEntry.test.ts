import { describe, expect, it, vi } from "vitest";

import { ApiRequestError } from "../src/api/requestSupport";
import {
  resolveAppEntryFromStatus,
  resolveAppEntryPath,
} from "../src/router/resolveAppEntry";

describe("resolveAppEntry", () => {
  it("empty 会话进入文本输入页", () => {
    expect(resolveAppEntryFromStatus("empty")).toBe("/text-input");
  });

  it("ready 会话进入工作区", () => {
    expect(resolveAppEntryFromStatus("ready")).toBe("/workspace");
  });

  it("initializing 会话进入工作区", () => {
    expect(resolveAppEntryFromStatus("initializing")).toBe("/workspace");
  });

  it("failed 会话也保留在工作区", () => {
    expect(resolveAppEntryFromStatus("failed")).toBe("/workspace");
  });

  it("根入口探测到 ready snapshot 时直达工作区", async () => {
    const loadSnapshot = vi.fn().mockResolvedValue({
      session_status: "ready",
    });

    await expect(resolveAppEntryPath(loadSnapshot as any)).resolves.toBe("/workspace");
  });

  it("snapshot 返回 404 时退回文本输入页", async () => {
    const loadSnapshot = vi.fn().mockRejectedValue(new ApiRequestError("missing", 404));

    await expect(resolveAppEntryPath(loadSnapshot as any)).resolves.toBe("/text-input");
  });

  it("snapshot 非 404 异常时回退到文本输入页", async () => {
    const loadSnapshot = vi.fn().mockRejectedValue(new ApiRequestError("network", null));
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    await expect(resolveAppEntryPath(loadSnapshot as any)).resolves.toBe("/text-input");
    expect(warn).toHaveBeenCalledOnce();

    warn.mockRestore();
  });
});
