import { describe, expect, it, vi } from "vitest";

const browserWindowSpy = vi.fn();
const showSpy = vi.fn();
const windowOnceSpy = vi.fn();
const webContentsOnceSpy = vi.fn();

vi.mock("electron", () => ({
  BrowserWindow: class {
    once = windowOnceSpy;
    show = showSpy;
    webContents = {
      once: webContentsOnceSpy,
    };

    constructor(options: unknown) {
      browserWindowSpy(options);
    }
  },
}));

describe("createMainWindow", () => {
  it("shows window when first page load fails so startup does not hang invisible", async () => {
    browserWindowSpy.mockReset();
    showSpy.mockReset();
    windowOnceSpy.mockReset();
    webContentsOnceSpy.mockReset();

    const { createMainWindow } = await import("../src/window/createMainWindow");

    createMainWindow();

    const failHandler = webContentsOnceSpy.mock.calls.find((args) => args[0] === "did-fail-load")?.[1];
    expect(typeof failHandler).toBe("function");

    failHandler();

    expect(showSpy).toHaveBeenCalledOnce();
  });

  it("sets a packaged window icon so the title bar uses the app icon", async () => {
    browserWindowSpy.mockReset();
    showSpy.mockReset();
    windowOnceSpy.mockReset();
    webContentsOnceSpy.mockReset();

    const { createMainWindow } = await import("../src/window/createMainWindow");

    createMainWindow();

    expect(browserWindowSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        icon: expect.stringContaining("512.ico"),
      }),
    );
  });
});
