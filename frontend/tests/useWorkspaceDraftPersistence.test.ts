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
      schemaVersion: 2,
      documentId: "doc-1",
      documentVersion: 3,
      segmentIds: ["seg-1", "seg-2"],
      mode: "editing",
      editorDoc: {
        type: "doc",
        content: [{ type: "paragraph", content: [{ type: "text", text: "正在编辑中的正文" }] }],
      },
      sourceDoc: {
        type: "doc",
        content: [
          {
            type: "paragraph",
            content: [
              {
                type: "text",
                text: "已规范化的第一段",
                marks: [{ type: "segmentAnchor", attrs: { segmentId: "seg-1" } }],
              },
              {
                type: "pauseBoundary",
                attrs: {
                  edgeId: "edge-1",
                  leftSegmentId: "seg-1",
                  rightSegmentId: "seg-2",
                  pauseDurationSeconds: 0.3,
                  boundaryStrategy: "crossfade",
                  layoutMode: "list",
                  crossBlock: false,
                },
              },
            ],
          },
          {
            type: "paragraph",
            content: [
              {
                type: "text",
                text: "已规范化的第二段",
                marks: [{ type: "segmentAnchor", attrs: { segmentId: "seg-2" } }],
              },
            ],
          },
        ],
      },
      segmentDrafts: { "seg-1": "已提交的第一段草稿" },
      effectiveText: "正在编辑中的正文",
      compositionLayoutHints: {
        basis: "source_text",
        segmentIdsByBlock: [["seg-1", "seg-2"]],
        sourceTextStatus: "aligned",
      },
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
      compositionLayoutHints: {
        basis: "source_text",
        segmentIdsByBlock: [["seg-1", "seg-2"]],
        sourceTextStatus: "aligned",
      },
    });
  });

  it("document_version 不一致时拒绝自动恢复", async () => {
    const { useWorkspaceDraftPersistence } = await loadPersistenceModule();
    const persistence = useWorkspaceDraftPersistence();

    persistence.saveSnapshot({
      schemaVersion: 2,
      documentId: "doc-1",
      documentVersion: 3,
      segmentIds: ["seg-1"],
      mode: "preview",
      editorDoc: {
        type: "doc",
        content: [{ type: "paragraph", content: [{ type: "text", text: "旧版本草稿" }] }],
      },
      sourceDoc: {
        type: "doc",
        content: [{ type: "paragraph", content: [{ type: "text", text: "旧版本草稿" }] }],
      },
      segmentDrafts: { "seg-1": "旧版本草稿" },
      effectiveText: "旧版本草稿",
      compositionLayoutHints: null,
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

  it("旧 schema 快照不再恢复，并会在读取时被清理", async () => {
    const { useWorkspaceDraftPersistence } = await loadPersistenceModule();
    const persistence = useWorkspaceDraftPersistence();

    localStorageMock.setItem(
      "neo-tts-workspace-local-draft::doc-legacy",
      JSON.stringify({
        schemaVersion: 1,
        documentId: "doc-legacy",
        documentVersion: 2,
        segmentIds: ["seg-1"],
        mode: "preview",
        editorDoc: {
          type: "doc",
          content: [{ type: "paragraph", content: [{ type: "text", text: "旧草稿" }] }],
        },
        segmentDrafts: { "seg-1": "旧草稿" },
        effectiveText: "旧草稿",
        updatedAt: "2026-04-08T09:00:00.000Z",
      }),
    );

    expect(persistence.readSnapshot("doc-legacy")).toBeNull();
    expect(
      localStorageMock.getItem("neo-tts-workspace-local-draft::doc-legacy"),
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
