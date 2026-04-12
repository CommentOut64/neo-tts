import { beforeEach, describe, expect, it, vi } from "vitest";

function createStorage() {
  const store = new Map<string, string>();

  return {
    getItem(key: string) {
      return store.has(key) ? store.get(key)! : null;
    },
    setItem(key: string, value: string) {
      store.set(key, value);
    },
    removeItem(key: string) {
      store.delete(key);
    },
    clear() {
      store.clear();
    },
  };
}

async function loadUseInputDraftModule() {
  vi.resetModules();
  return import("../src/composables/useInputDraft");
}

describe("useInputDraft", () => {
  const localStorageMock = createStorage();

  beforeEach(() => {
    localStorageMock.clear();
    vi.stubGlobal("window", {
      localStorage: localStorageMock,
    });
  });

  it("输入正文后会立即持久化到 localStorage", async () => {
    const { useInputDraft } = await loadUseInputDraftModule();
    const draft = useInputDraft();

    draft.setText("第一句。第二句。");

    expect(localStorageMock.getItem("neo-tts-input-draft")).toBeTruthy();
    expect(draft.text.value).toBe("第一句。第二句。");
    expect(draft.source.value).toBe("manual");
  });

  it("刷新后会从 localStorage 恢复正文草稿", async () => {
    localStorageMock.setItem(
      "neo-tts-input-draft",
      JSON.stringify({
        text: "刷新前的正文",
        draftRevision: 3,
        lastSentToSessionRevision: 1,
      }),
    );

    const { useInputDraft } = await loadUseInputDraftModule();
    const draft = useInputDraft();

    expect(draft.text.value).toBe("刷新前的正文");
    expect(draft.draftRevision.value).toBe(3);
    expect(draft.lastSentToSessionRevision.value).toBe(1);
    expect(draft.source.value).toBe("manual");
  });

  it("清空正文时会移除持久化缓存", async () => {
    const { useInputDraft } = await loadUseInputDraftModule();
    const draft = useInputDraft();

    draft.setText("临时正文");
    draft.setText("");

    expect(localStorageMock.getItem("neo-tts-input-draft")).toBeNull();
  });

  it("会持久化输入页文本语言，并在重新加载后恢复", async () => {
    const { useInputDraft } = await loadUseInputDraftModule();
    const draft = useInputDraft();

    draft.setTextLanguage("ja");

    expect(localStorageMock.getItem("neo-tts-input-draft")).toContain('"textLanguage":"ja"');

    const reloadedModule = await loadUseInputDraftModule();
    const reloadedDraft = reloadedModule.useInputDraft();

    expect(reloadedDraft.textLanguage.value).toBe("ja");
  });

  it("没有正文时，非 auto 语言配置仍会保留持久化状态", async () => {
    const { useInputDraft } = await loadUseInputDraftModule();
    const draft = useInputDraft();

    draft.setTextLanguage("zh");
    draft.setText("临时正文");
    draft.setText("");

    expect(localStorageMock.getItem("neo-tts-input-draft")).toContain('"textLanguage":"zh"');
  });

  it("从正式正文回填后也会同步持久化，并记录为 applied_text 来源", async () => {
    const { useInputDraft } = await loadUseInputDraftModule();
    const draft = useInputDraft();

    draft.backfillFromAppliedText("来自正式正文");
    draft.markSentToSession(draft.draftRevision.value);

    expect(draft.text.value).toBe("来自正式正文");
    expect(draft.source.value).toBe("applied_text");
    expect(localStorageMock.getItem("neo-tts-input-draft")).toContain("来自正式正文");
  });

  it("显式保留 workspace 文字时，会记录为 input_handoff 来源", async () => {
    const { useInputDraft } = await loadUseInputDraftModule();
    const draft = useInputDraft();

    draft.handoffFromWorkspace("来自 workspace 的保留文字");

    expect(draft.text.value).toBe("来自 workspace 的保留文字");
    expect(draft.source.value).toBe("input_handoff");
  });

  it("会记住最近一轮会话最初版本，并允许跨重新加载恢复", async () => {
    const { useInputDraft } = await loadUseInputDraftModule();
    const draft = useInputDraft();

    draft.rememberLastSessionInitialText("第一次进入会话时的正文");
    draft.setText("");

    const persisted = localStorageMock.getItem("neo-tts-input-draft");
    expect(persisted).toContain("第一次进入会话时的正文");

    const reloadedModule = await loadUseInputDraftModule();
    const reloadedDraft = reloadedModule.useInputDraft();
    const restored = reloadedDraft.restoreLastSessionInitialText();

    expect(restored).toBe(true);
    expect(reloadedDraft.text.value).toBe("第一次进入会话时的正文");
    expect(draft.source.value).toBe("manual");
  });
});
