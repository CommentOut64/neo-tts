import { beforeEach, describe, expect, it, vi } from "vitest";

const systemApiMock = vi.hoisted(() => ({
  openFileDialog: vi.fn(),
}));

vi.mock("@/api/system", () => systemApiMock);

describe("fileSelection bridge", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    Reflect.deleteProperty(globalThis, "window");
  });

  it("在 electron bridge 存在时返回本地绝对路径", async () => {
    const file = new File(["demo"], "model.ckpt");
    const getPathForFile = vi
      .fn()
      .mockReturnValue("F:/GPT-SoVITS-v2pro-20250604/model.ckpt");
    Object.defineProperty(globalThis, "window", {
      value: {
        neoTTS: {
          runtime: "electron",
          distributionKind: "portable",
          backendOrigin: "http://127.0.0.1:18600",
          requestAppExit: vi.fn(),
          openExternalUrl: vi.fn(),
          getPathForFile,
        },
      },
      configurable: true,
    });

    const { resolveAbsolutePathForFile } = await import(
      "../src/platform/fileSelection"
    );

    expect(resolveAbsolutePathForFile(file)).toBe(
      "F:/GPT-SoVITS-v2pro-20250604/model.ckpt",
    );
    expect(getPathForFile).toHaveBeenCalledWith(file);
  });

  it("在非 electron 或 bridge 缺失时返回 null", async () => {
    const { resolveAbsolutePathForFile } = await import(
      "../src/platform/fileSelection"
    );

    expect(resolveAbsolutePathForFile(new File(["demo"], "model.ckpt"))).toBeNull();
  });

  it("在非 electron 环境点击选择时会走后端文件对话框", async () => {
    systemApiMock.openFileDialog.mockResolvedValue(
      "F:/GPT-SoVITS-v2pro-20250604/demo.ckpt",
    );

    const { selectAbsolutePathForFile } = await import(
      "../src/platform/fileSelection"
    );

    await expect(
      selectAbsolutePathForFile({
        accept: ".ckpt",
      }),
    ).resolves.toEqual({
      name: "demo.ckpt",
      absolutePath: "F:/GPT-SoVITS-v2pro-20250604/demo.ckpt",
    });
    expect(systemApiMock.openFileDialog).toHaveBeenCalledWith(".ckpt", undefined);
  });
});
