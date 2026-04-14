import { beforeEach, describe, expect, it, vi } from "vitest";

describe("runtimeConfig", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
    Reflect.deleteProperty(globalThis, "window");
  });

  it("prefers preload-provided backend origin in electron runtime", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "http://127.0.0.1:9999");
    Object.defineProperty(globalThis, "window", {
      value: {
        neoTTS: {
          runtime: "electron",
          distributionKind: "portable",
          backendOrigin: "http://127.0.0.1:18600",
          requestAppExit: vi.fn(),
        },
      },
      configurable: true,
    });

    const { getRuntimeConfig, resolveBackendUrl } = await import("../src/platform/runtimeConfig");

    expect(getRuntimeConfig()).toEqual({
      runtime: "electron",
      distributionKind: "portable",
      backendOrigin: "http://127.0.0.1:18600",
    });
    expect(resolveBackendUrl("/v1/audio/inference/progress")).toBe(
      "http://127.0.0.1:18600/v1/audio/inference/progress",
    );
  });

  it("exposes installed or portable distribution kind", async () => {
    Object.defineProperty(globalThis, "window", {
      value: {
        neoTTS: {
          runtime: "electron",
          distributionKind: "installed",
          backendOrigin: "http://127.0.0.1:18600",
          requestAppExit: vi.fn(),
        },
      },
      configurable: true,
    });

    const { getRuntimeConfig } = await import("../src/platform/runtimeConfig");

    expect(getRuntimeConfig().distributionKind).toBe("installed");
  });
});
