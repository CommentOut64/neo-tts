import { describe, expect, it } from "vitest";

import { resolveInputDraftSyncAction } from "../src/composables/useEditSession";

describe("useEditSession draft sync", () => {
  it("输入稿为空时会从 session 正文回填", () => {
    expect(
      resolveInputDraftSyncAction({
        sessionHeadText: "会话正文",
        inputText: "",
        isInputEmpty: true,
        draftRevision: 0,
        lastSentToSessionRevision: null,
        sourceDraftRevision: null,
      }),
    ).toBe("backfill");
  });

  it("输入稿首次与 session 正文一致时只采纳版本，不重复回填", () => {
    expect(
      resolveInputDraftSyncAction({
        sessionHeadText: "会话正文",
        inputText: "会话正文",
        isInputEmpty: false,
        draftRevision: 4,
        lastSentToSessionRevision: null,
        sourceDraftRevision: null,
      }),
    ).toBe("adopt");
  });

  it("当输入稿仍在跟随 session 时，会话正文变化后会自动同步", () => {
    expect(
      resolveInputDraftSyncAction({
        sessionHeadText: "新的会话正文",
        inputText: "旧的会话正文",
        isInputEmpty: false,
        draftRevision: 6,
        lastSentToSessionRevision: 6,
        sourceDraftRevision: 6,
      }),
    ).toBe("backfill");
  });

  it("当 text-input 已有独立未提交改动时，不会被 session 覆盖", () => {
    expect(
      resolveInputDraftSyncAction({
        sessionHeadText: "会话正文",
        inputText: "text-input 自己的新稿",
        isInputEmpty: false,
        draftRevision: 8,
        lastSentToSessionRevision: 6,
        sourceDraftRevision: 6,
      }),
    ).toBe("noop");
  });
});
