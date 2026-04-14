import { beforeEach, describe, expect, it, vi } from "vitest";

const systemApiMock = vi.hoisted(() => ({
  prepareExit: vi.fn().mockResolvedValue({
    status: "prepared",
    launcher_exit_requested: false,
    active_render_job_status: null,
    inference_status: "idle",
  }),
}));

vi.mock("@/api/system", () => systemApiMock);

describe("runtimeHost", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    Reflect.deleteProperty(globalThis, "window");
  });

  it("web host exits through backend prepare-exit", async () => {
    const { getRuntimeHost } = await import("../src/platform/runtimeHost");

    const host = getRuntimeHost();
    const result = await host.requestExit();

    expect(host.kind).toBe("web");
    expect(systemApiMock.prepareExit).toHaveBeenCalledTimes(1);
    expect(result.launcherExitRequested).toBe(false);
  });

  it("electron host exits through preload bridge instead of direct HTTP ownership", async () => {
    const requestAppExit = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(globalThis, "window", {
      value: {
        neoTTS: {
          runtime: "electron",
          requestAppExit,
        },
      },
      configurable: true,
    });

    const { getRuntimeHost } = await import("../src/platform/runtimeHost");

    const host = getRuntimeHost();
    const result = await host.requestExit();

    expect(host.kind).toBe("electron");
    expect(requestAppExit).toHaveBeenCalledTimes(1);
    expect(systemApiMock.prepareExit).not.toHaveBeenCalled();
    expect(result.launcherExitRequested).toBe(true);
  });
});
