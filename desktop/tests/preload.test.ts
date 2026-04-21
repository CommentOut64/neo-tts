import { beforeEach, describe, expect, it, vi } from "vitest";

const exposeInMainWorld = vi.fn();
const sendSync = vi.fn();
const invoke = vi.fn();
const getPathForFile = vi.fn();

vi.mock("electron", () => ({
  contextBridge: {
    exposeInMainWorld,
  },
  ipcRenderer: {
    sendSync,
    invoke,
  },
  webUtils: {
    getPathForFile,
  },
}));

describe("desktop preload", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    sendSync.mockReturnValue({
      runtime: "electron",
      distributionKind: "portable",
      backendOrigin: "http://127.0.0.1:18600",
    });
  });

  it("暴露供前端解析本地文件绝对路径的 bridge", async () => {
    const fakeFile = new File(["demo"], "model.ckpt");
    getPathForFile.mockReturnValue("F:/GPT-SoVITS-v2pro-20250604/model.ckpt");

    await import("../src/preload");

    expect(exposeInMainWorld).toHaveBeenCalledOnce();
    const [, bridge] = exposeInMainWorld.mock.calls[0]!;
    expect(typeof bridge.getPathForFile).toBe("function");
    expect(bridge.getPathForFile(fakeFile)).toBe(
      "F:/GPT-SoVITS-v2pro-20250604/model.ckpt",
    );
    expect(getPathForFile).toHaveBeenCalledWith(fakeFile);
  });
});
