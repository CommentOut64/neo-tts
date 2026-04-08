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

async function loadPersistenceModule() {
  vi.resetModules();
  return import("../src/composables/useWorkspaceDraftPersistence");
}

describe("useWorkspaceDraftPersistence", () => {
  const localStorageMock = createStorage();

  beforeEach(() => {
    localStorageMock.clear();
    vi.stubGlobal("window", {
      localStorage: localStorageMock,
    });
  });

  it("能保存并按严格匹配恢复工作区草稿快照", async () => {
    const { useWorkspaceDraftPersistence } = await loadPersistenceModule();
    const persistence = useWorkspaceDraftPersistence();

    persistence.saveSnapshot({
      schemaVersion: 1,
      documentId: "doc-1",
      documentVersion: 3,
      segmentIds: ["seg-1", "seg-2"],
      mode: "editing",
      editorDoc: {
        type: "doc",
        content: [{ type: "paragraph", content: [{ type: "text", text: "正在编辑中的正文" }] }],
      },
      segmentDrafts: { "seg-1": "已提交的第一段草稿" },
      effectiveText: "正在编辑中的正文",
      updatedAt: "2026-04-08T09:00:00.000Z",
    });

    expect(
      persistence.readCompatibleSnapshot({
        documentId: "doc-1",
        documentVersion: 3,
        segmentIds: ["seg-1", "seg-2"],
      }),
    ).toMatchObject({
      mode: "editing",
      effectiveText: "正在编辑中的正文",
      segmentDrafts: { "seg-1": "已提交的第一段草稿" },
    });
  });

  it("document_version 不一致时拒绝自动恢复", async () => {
    const { useWorkspaceDraftPersistence } = await loadPersistenceModule();
    const persistence = useWorkspaceDraftPersistence();

    persistence.saveSnapshot({
      schemaVersion: 1,
      documentId: "doc-1",
      documentVersion: 3,
      segmentIds: ["seg-1"],
      mode: "preview",
      editorDoc: {
        type: "doc",
        content: [{ type: "paragraph", content: [{ type: "text", text: "旧版本草稿" }] }],
      },
      segmentDrafts: { "seg-1": "旧版本草稿" },
      effectiveText: "旧版本草稿",
      updatedAt: "2026-04-08T09:00:00.000Z",
    });

    expect(
      persistence.readCompatibleSnapshot({
        documentId: "doc-1",
        documentVersion: 4,
        segmentIds: ["seg-1"],
      }),
    ).toBeNull();
  });

  it("快照损坏时会自动清理本地缓存", async () => {
    const { useWorkspaceDraftPersistence } = await loadPersistenceModule();
    const persistence = useWorkspaceDraftPersistence();

    localStorageMock.setItem("neo-tts-workspace-local-draft::doc-1", "{bad json");

    expect(persistence.readSnapshot("doc-1")).toBeNull();
    expect(localStorageMock.getItem("neo-tts-workspace-local-draft::doc-1")).toBeNull();
  });
});
