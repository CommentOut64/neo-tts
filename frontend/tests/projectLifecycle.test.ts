import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  createProject: vi.fn(),
  openProject: vi.fn(),
  saveProject: vi.fn(),
  saveProjectAs: vi.fn(),
  importLegacyProject: vi.fn(),
}));

vi.mock("@/api/projects", () => apiMock);

function response(overrides: Record<string, unknown> = {}) {
  return {
    ok: true,
    project_id: "p1",
    workspace_id: "w1",
    save_revision: 1,
    dirty: false,
    capability: { play: true, export: true, edit: true, render: true, boundary: true },
    ...overrides,
  };
}

describe("useProjectLifecycle", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
  });

  it("保存前执行捕获，成功后更新 revision", async () => {
    apiMock.saveProject.mockResolvedValue(response({ save_revision: 2 }));
    const { useProjectLifecycle } = await import("../src/composables/useProjectLifecycle");
    const capture = vi.fn().mockResolvedValue({ project: { project_id: "p1" } });
    const flushDraft = vi.fn();
    const lifecycle = useProjectLifecycle({ capture, flushDraft });

    lifecycle.markDirty(true);
    await expect(lifecycle.save()).resolves.toMatchObject({ save_revision: 2 });

    expect(capture).toHaveBeenCalledOnce();
    expect(flushDraft).toHaveBeenCalledOnce();
    expect(apiMock.saveProject).toHaveBeenCalledWith({ project: { project_id: "p1" } }, undefined);
    expect(lifecycle.saveRevision.value).toBe(2);
    expect(lifecycle.dirty.value).toBe(false);
  });

  it("保存失败保留 dirty 并暴露错误", async () => {
    apiMock.saveProject.mockRejectedValue(new Error("disk full"));
    const { useProjectLifecycle } = await import("../src/composables/useProjectLifecycle");
    const lifecycle = useProjectLifecycle({ capture: () => ({ project: {} }) });
    lifecycle.markDirty(true);

    await expect(lifecycle.save()).resolves.toBeNull();

    expect(lifecycle.dirty.value).toBe(true);
    expect(lifecycle.lastError.value?.code).toBe("PROJECT_REQUEST_FAILED");
  });

  it("打开只读降级项目后安装能力集", async () => {
    apiMock.openProject.mockResolvedValue(response({
      project: { project_id: "p1" },
      capability: { play: true, export: true, edit: false, render: false, boundary: false },
      dirty: false,
    }));
    const { useProjectLifecycle } = await import("../src/composables/useProjectLifecycle");
    const restore = vi.fn();
    const lifecycle = useProjectLifecycle({ restore });

    await lifecycle.open("F:/projects/demo.neo");

    expect(restore).toHaveBeenCalledWith({ project_id: "p1" });
    expect(lifecycle.readOnly.value).toBe(true);
    expect(lifecycle.capability.value.edit).toBe(false);
  });
});
