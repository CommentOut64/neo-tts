import { describe, expect, it, vi } from "vitest";

const browserWindowSpy = vi.fn();
const showSpy = vi.fn();
const windowOnceSpy = vi.fn();
const webContentsOnceSpy = vi.fn();
const webContentsOnSpy = vi.fn();
const setWindowOpenHandlerSpy = vi.fn();
const getUrlSpy = vi.fn(() => "http://127.0.0.1:18600/workspace");
const openExternalSpy = vi.fn();

vi.mock("electron", () => ({
  BrowserWindow: class {
    once = windowOnceSpy;
    show = showSpy;
    webContents = {
      once: webContentsOnceSpy,
      on: webContentsOnSpy,
      setWindowOpenHandler: setWindowOpenHandlerSpy,
      getURL: getUrlSpy,
    };

    constructor(options: unknown) {
      browserWindowSpy(options);
    }
  },
  shell: {
    openExternal: openExternalSpy,
  },
}));

describe("createMainWindow", () => {
  it("denies window.open and forwards external urls to the default browser", async () => {
    vi.resetModules();
    browserWindowSpy.mockReset();
    showSpy.mockReset();
    windowOnceSpy.mockReset();
    webContentsOnceSpy.mockReset();
    webContentsOnSpy.mockReset();
    setWindowOpenHandlerSpy.mockReset();
    getUrlSpy.mockReset();
    getUrlSpy.mockReturnValue("http://127.0.0.1:18600/workspace");
    openExternalSpy.mockReset();

    const { createMainWindow } = await import("../src/window/createMainWindow");

    createMainWindow();

    const openHandler = setWindowOpenHandlerSpy.mock.calls[0]?.[0];
    expect(typeof openHandler).toBe("function");

    const result = openHandler({ url: "https://github.com/CommentOut64/neo-tts" });

    expect(result).toEqual({ action: "deny" });
    expect(openExternalSpy).toHaveBeenCalledWith("https://github.com/CommentOut64/neo-tts");
  });

  it("prevents main-window navigation away from the app origin and opens it externally", async () => {
    vi.resetModules();
    browserWindowSpy.mockReset();
    showSpy.mockReset();
    windowOnceSpy.mockReset();
    webContentsOnceSpy.mockReset();
    webContentsOnSpy.mockReset();
    setWindowOpenHandlerSpy.mockReset();
    getUrlSpy.mockReset();
    getUrlSpy.mockReturnValue("http://127.0.0.1:18600/workspace");
    openExternalSpy.mockReset();

    const { createMainWindow } = await import("../src/window/createMainWindow");

    createMainWindow();

    const navigateHandler = webContentsOnSpy.mock.calls.find((args) => args[0] === "will-navigate")?.[1];
    expect(typeof navigateHandler).toBe("function");

    const event = {
      preventDefault: vi.fn(),
    };
    navigateHandler(event, "https://space.bilibili.com/515407408");

    expect(event.preventDefault).toHaveBeenCalledOnce();
    expect(openExternalSpy).toHaveBeenCalledWith("https://space.bilibili.com/515407408");
  });

  it("shows window when first page load fails so startup does not hang invisible", async () => {
    vi.resetModules();
    browserWindowSpy.mockReset();
    showSpy.mockReset();
    windowOnceSpy.mockReset();
    webContentsOnceSpy.mockReset();
    webContentsOnSpy.mockReset();
    setWindowOpenHandlerSpy.mockReset();
    getUrlSpy.mockReset();
    getUrlSpy.mockReturnValue("http://127.0.0.1:18600/workspace");
    openExternalSpy.mockReset();

    const { createMainWindow } = await import("../src/window/createMainWindow");

    createMainWindow();

    const failHandler = webContentsOnceSpy.mock.calls.find((args) => args[0] === "did-fail-load")?.[1];
    expect(typeof failHandler).toBe("function");

    failHandler();

    expect(showSpy).toHaveBeenCalledOnce();
  });

  it("shows window after a startup timeout fallback when no renderer event arrives", async () => {
    vi.resetModules();
    vi.useFakeTimers();
    browserWindowSpy.mockReset();
    showSpy.mockReset();
    windowOnceSpy.mockReset();
    webContentsOnceSpy.mockReset();
    webContentsOnSpy.mockReset();
    setWindowOpenHandlerSpy.mockReset();
    getUrlSpy.mockReset();
    getUrlSpy.mockReturnValue("http://127.0.0.1:18600/workspace");
    openExternalSpy.mockReset();

    const { createMainWindow } = await import("../src/window/createMainWindow");

    createMainWindow();
    expect(showSpy).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(3_000);

    expect(showSpy).toHaveBeenCalledOnce();
    vi.useRealTimers();
  });

  it("sets a packaged window icon so the title bar uses the app icon", async () => {
    vi.resetModules();
    browserWindowSpy.mockReset();
    showSpy.mockReset();
    windowOnceSpy.mockReset();
    webContentsOnceSpy.mockReset();
    webContentsOnSpy.mockReset();
    setWindowOpenHandlerSpy.mockReset();
    getUrlSpy.mockReset();
    getUrlSpy.mockReturnValue("http://127.0.0.1:18600/workspace");
    openExternalSpy.mockReset();

    const { createMainWindow } = await import("../src/window/createMainWindow");

    createMainWindow();

    expect(browserWindowSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        icon: expect.stringContaining("512.ico"),
      }),
    );
  });
});
