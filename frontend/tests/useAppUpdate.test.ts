import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { systemApiMock, elementPlusMock } = vi.hoisted(() => ({
  systemApiMock: {
    getVersion: vi.fn().mockResolvedValue({ version: "0.0.1" }),
    checkForAppUpdate: vi.fn(),
    startAppUpdateDownload: vi.fn(),
    restartAndApplyAppUpdate: vi.fn(),
  },
  elementPlusMock: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
}));

vi.mock("@/api/system", () => systemApiMock);
vi.mock("element-plus", () => ({
  ElMessage: {
    success: elementPlusMock.success,
    error: elementPlusMock.error,
    info: elementPlusMock.info,
  },
}));

function createStorage() {
  const store = new Map<string, string>();
  return {
    getItem: vi.fn((key: string) => (store.has(key) ? store.get(key)! : null)),
    setItem: vi.fn((key: string, value: string) => {
      store.set(key, value);
    }),
    removeItem: vi.fn((key: string) => {
      store.delete(key);
    }),
    clear: vi.fn(() => {
      store.clear();
    }),
  };
}

describe("useAppUpdate", () => {
  const localStorageMock = createStorage();

  beforeEach(() => {
    vi.resetModules();
    systemApiMock.getVersion.mockReset();
    systemApiMock.checkForAppUpdate.mockReset();
    systemApiMock.startAppUpdateDownload.mockReset();
    systemApiMock.restartAndApplyAppUpdate.mockReset();
    elementPlusMock.success.mockReset();
    elementPlusMock.error.mockReset();
    elementPlusMock.info.mockReset();
    localStorageMock.clear();
    vi.stubGlobal("localStorage", localStorageMock);
    systemApiMock.getVersion.mockResolvedValue({ version: "0.0.1" });
    systemApiMock.checkForAppUpdate.mockResolvedValue({ status: "up-to-date" });
    systemApiMock.startAppUpdateDownload.mockResolvedValue({ status: "ready-to-restart" });
    systemApiMock.restartAndApplyAppUpdate.mockResolvedValue({ status: "switching" });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("adds a v prefix when the backend version is a plain semantic version", async () => {
    const { formatVersionLabel } = await import("../src/composables/useAppUpdate");
    expect(formatVersionLabel("0.0.1")).toBe("v0.0.1");
  });

  it("preserves an existing v prefix", async () => {
    const { formatVersionLabel } = await import("../src/composables/useAppUpdate");
    expect(formatVersionLabel("v0.0.1")).toBe("v0.0.1");
  });

  it("stores layered update metadata when bootstrap reports update-available", async () => {
    systemApiMock.checkForAppUpdate.mockResolvedValue({
      status: "update-available",
      releaseId: "v0.0.2",
      notesUrl: "https://example.com/release-notes",
      changedPackages: ["shell", "app-core"],
      estimatedDownloadBytes: 300,
    });

    const { useAppUpdate } = await import("../src/composables/useAppUpdate");
    const appUpdate = useAppUpdate();

    await appUpdate.handleCheckUpdate(false);

    expect(appUpdate.updateState.value).toEqual(
      expect.objectContaining({
        status: "update-available",
        releaseId: "v0.0.2",
        changedPackages: ["shell", "app-core"],
      }),
    );
    expect(appUpdate.isUpdateDialogVisible.value).toBe(true);
  });

  it("shows a success toast when bootstrap reports up-to-date on manual check", async () => {
    const { useAppUpdate } = await import("../src/composables/useAppUpdate");
    const appUpdate = useAppUpdate();

    await appUpdate.handleCheckUpdate(false);

    expect(elementPlusMock.success).toHaveBeenCalledWith("当前已是最新版本");
    expect(appUpdate.updateState.value.status).toBe("up-to-date");
  });

  it("persists ignored release id and suppresses the same release during silent checks", async () => {
    systemApiMock.checkForAppUpdate.mockResolvedValue({
      status: "update-available",
      releaseId: "v0.0.3",
      changedPackages: ["runtime"],
    });

    const { useAppUpdate } = await import("../src/composables/useAppUpdate");
    const appUpdate = useAppUpdate();

    await appUpdate.handleCheckUpdate(false);
    appUpdate.ignoreUpdate();

    expect(localStorageMock.setItem).toHaveBeenCalled();
    await appUpdate.handleCheckUpdate(true);

    expect(appUpdate.isUpdateDialogVisible.value).toBe(false);
    expect(appUpdate.updateState.value.status).toBe("idle");
  });

  it("enters ready-to-restart after bootstrap finishes staging the selected release", async () => {
    systemApiMock.checkForAppUpdate.mockResolvedValue({
      status: "update-available",
      releaseId: "v0.0.4",
      changedPackages: ["shell"],
    });

    const { useAppUpdate } = await import("../src/composables/useAppUpdate");
    const appUpdate = useAppUpdate();

    await appUpdate.handleCheckUpdate(false);
    await appUpdate.startUpdateDownload();

    expect(systemApiMock.startAppUpdateDownload).toHaveBeenCalledWith({ releaseId: "v0.0.4" });
    expect(appUpdate.updateState.value.status).toBe("ready-to-restart");
  });

  it("delegates restart-and-apply to the desktop bridge when update is ready", async () => {
    const { useAppUpdate } = await import("../src/composables/useAppUpdate");
    const appUpdate = useAppUpdate();
    appUpdate.updateState.value = {
      status: "ready-to-restart",
      releaseId: "v0.0.5",
      changedPackages: ["shell"],
    };

    await appUpdate.restartAndApplyUpdate();

    expect(systemApiMock.restartAndApplyAppUpdate).toHaveBeenCalledWith({ releaseId: "v0.0.5" });
    expect(appUpdate.updateState.value.status).toBe("switching");
  });

  it("polls bootstrap while layered download is running and keeps package progress in sync", async () => {
    vi.useFakeTimers();
    systemApiMock.checkForAppUpdate
      .mockResolvedValueOnce({
        status: "update-available",
        releaseId: "v0.0.6",
        changedPackages: ["shell", "app-core"],
        estimatedDownloadBytes: 2048,
      })
      .mockResolvedValueOnce({
        status: "downloading",
        releaseId: "v0.0.6",
        changedPackages: ["shell", "app-core"],
        progress: {
          totalPackages: 2,
          completedPackages: 1,
          currentPackageId: "app-core",
          currentPackageVersion: "v0.0.6",
        },
      })
      .mockResolvedValueOnce({
        status: "ready-to-restart",
        releaseId: "v0.0.6",
        changedPackages: ["shell", "app-core"],
        progress: {
          totalPackages: 2,
          completedPackages: 2,
        },
      });
    systemApiMock.startAppUpdateDownload.mockResolvedValue({
      status: "downloading",
      progress: {
        totalPackages: 2,
        completedPackages: 0,
        currentPackageId: "shell",
        currentPackageVersion: "v0.0.6",
      },
    });

    const { useAppUpdate } = await import("../src/composables/useAppUpdate");
    const appUpdate = useAppUpdate();

    await appUpdate.handleCheckUpdate(false);
    await appUpdate.startUpdateDownload();
    expect(appUpdate.updateState.value.status).toBe("downloading");
    expect(appUpdate.updateState.value.progress).toEqual(
      expect.objectContaining({
        totalPackages: 2,
        completedPackages: 0,
        currentPackageId: "shell",
      }),
    );

    await vi.advanceTimersByTimeAsync(1_000);
    expect(appUpdate.updateState.value.status).toBe("downloading");
    expect(appUpdate.updateState.value.progress).toEqual(
      expect.objectContaining({
        totalPackages: 2,
        completedPackages: 1,
        currentPackageId: "app-core",
      }),
    );

    await vi.advanceTimersByTimeAsync(1_000);
    expect(appUpdate.updateState.value.status).toBe("ready-to-restart");
    expect(appUpdate.updateState.value.progress).toEqual(
      expect.objectContaining({
        totalPackages: 2,
        completedPackages: 2,
      }),
    );
  });

  it("preserves rollback failure metadata returned by bootstrap check", async () => {
    systemApiMock.checkForAppUpdate.mockResolvedValue({
      status: "error",
      releaseId: "v0.0.7",
      errorCode: "switch-failed",
      errorMessage: "检测到上次切换失败，已回滚到稳定版本。",
    });

    const { useAppUpdate } = await import("../src/composables/useAppUpdate");
    const appUpdate = useAppUpdate();

    await appUpdate.handleCheckUpdate(false);

    expect(appUpdate.updateState.value).toEqual(
      expect.objectContaining({
        status: "error",
        releaseId: "v0.0.7",
        errorCode: "switch-failed",
        errorMessage: "检测到上次切换失败，已回滚到稳定版本。",
      }),
    );
  });
});
