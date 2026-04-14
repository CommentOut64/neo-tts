import axios from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

describe("http runtime config", () => {
  beforeEach(() => {
    vi.resetModules();
    Reflect.deleteProperty(globalThis, "window");
    axios.defaults.baseURL = undefined;
    axios.defaults.timeout = 0;
  });

  it("configures default axios baseURL from the electron preload bridge", async () => {
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

    await import("../src/api/http");

    expect(axios.defaults.baseURL).toBe("http://127.0.0.1:18600");
    expect(axios.defaults.timeout).toBe(30_000);
  });
});
