import { describe, expect, it, vi } from "vitest";

import { createParameterPatchQueue } from "../src/components/workspace/parameter-panel/submitParameterPatchQueue";

describe("createParameterPatchQueue", () => {
  it("会按顺序提交每个 patch 任务", async () => {
    const events: string[] = [];

    const queue = createParameterPatchQueue();
    await queue.run([
      {
        kind: "voice-binding",
        submit: async () => {
          events.push("submit-voice");
          events.push("done-voice");
        },
      },
      {
        kind: "render-profile",
        submit: async () => {
          events.push("submit-profile");
          events.push("done-profile");
        },
      },
    ]);

    expect(events).toEqual([
      "submit-voice",
      "done-voice",
      "submit-profile",
      "done-profile",
    ]);
  });

  it("遇到失败后会停止后续 patch", async () => {
    const secondSubmit = vi.fn();
    const queue = createParameterPatchQueue();

    const result = await queue.run([
      {
        kind: "voice-binding",
        submit: async () => {
          throw new Error("failed");
        },
      },
      {
        kind: "render-profile",
        submit: async () => {
          secondSubmit();
        },
      },
    ]);

    expect(result.status).toBe("failed");
    expect(result.failedTaskKind).toBe("voice-binding");
    expect(result.error).toBeInstanceOf(Error);
    expect(secondSubmit).not.toHaveBeenCalled();
  });
});
