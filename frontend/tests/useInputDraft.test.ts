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

  it("从会话回填正文后也会同步持久化", async () => {
    const { useInputDraft } = await loadUseInputDraftModule();
    const draft = useInputDraft();

    draft.backfillFromSession("来自会话的正文");
    draft.markSentToSession(draft.draftRevision.value);

    expect(draft.text.value).toBe("来自会话的正文");
    expect(draft.source.value).toBe("session");
    expect(localStorageMock.getItem("neo-tts-input-draft")).toContain("来自会话的正文");
  });

  it("workspace 草稿会更新输入框，并记录为 workspace 来源", async () => {
    const { useInputDraft } = await loadUseInputDraftModule();
    const draft = useInputDraft();

    draft.syncFromWorkspaceDraft("来自 workspace 的正文");

    expect(draft.text.value).toBe("来自 workspace 的正文");
    expect(draft.source.value).toBe("workspace");
  });

  it("文本输入页手工改动后，workspace 不会再静默覆盖", async () => {
    const { useInputDraft } = await loadUseInputDraftModule();
    const draft = useInputDraft();

    draft.syncFromWorkspaceDraft("旧的 workspace 正文");
    draft.setText("text-input 自己的新稿");
    const applied = draft.syncFromWorkspaceDraft("新的 workspace 正文");

    expect(applied).toBe(false);
    expect(draft.text.value).toBe("text-input 自己的新稿");
    expect(draft.source.value).toBe("manual");
  });
});
