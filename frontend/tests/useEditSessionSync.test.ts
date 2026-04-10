import { describe, expect, it } from "vitest";

import { resolveInputDraftSyncAction } from "../src/composables/useEditSession";

describe("useEditSession draft sync", () => {
  it("输入稿为空时会从 session 正文回填", () => {
    expect(
      resolveInputDraftSyncAction({
        sessionHeadText: "会话正文",
        inputText: "",
        inputSource: "manual",
        isInputEmpty: true,
        draftRevision: 0,
        lastSentToSessionRevision: null,
        sourceDraftRevision: null,
      }),
    ).toBe("backfill");
  });

  it("用户显式清空输入稿后，不会在切页时被 session 正文重新回填", () => {
    expect(
      resolveInputDraftSyncAction({
        sessionHeadText: "会话正文",
        inputText: "",
        inputSource: "manual",
        isInputEmpty: true,
        draftRevision: 9,
        lastSentToSessionRevision: 6,
        sourceDraftRevision: 6,
      }),
    ).toBe("noop");
  });

  it("输入稿首次与正式正文一致时只采纳版本，不重复回填", () => {
    expect(
      resolveInputDraftSyncAction({
        sessionHeadText: "会话正文",
        inputText: "会话正文",
        inputSource: "manual",
        isInputEmpty: false,
        draftRevision: 4,
        lastSentToSessionRevision: null,
        sourceDraftRevision: null,
      }),
    ).toBe("adopt");
  });

  it("当输入稿仍在跟随 applied_text 时，正式正文变化后会自动同步", () => {
    expect(
      resolveInputDraftSyncAction({
        sessionHeadText: "新的会话正文",
        inputText: "旧的会话正文",
        inputSource: "applied_text",
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
        inputSource: "manual",
        isInputEmpty: false,
        draftRevision: 8,
        lastSentToSessionRevision: 6,
        sourceDraftRevision: 6,
      }),
    ).toBe("noop");
  });

  it("当输入框文字来自结束会话的 handoff 时，不会被正式正文静默覆盖", () => {
    expect(
      resolveInputDraftSyncAction({
        sessionHeadText: "新的会话正文",
        inputText: "结束会话时保留的文字",
        inputSource: "input_handoff",
        isInputEmpty: false,
        draftRevision: 10,
        lastSentToSessionRevision: 8,
        sourceDraftRevision: 8,
      }),
    ).toBe("noop");
  });
});
