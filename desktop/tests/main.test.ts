import path from "node:path";
import fs from "node:fs";
import os from "node:os";
import { describe, expect, it, vi } from "vitest";

import { APP_OPEN_EXTERNAL_URL_CHANNEL, APP_REQUEST_EXIT_CHANNEL } from "../src/ipc/channels";
import { runMain } from "../src/main";
import type { ProductPaths } from "../src/runtime/paths";

type AppStub = {
  requestSingleInstanceLock: () => boolean;
  whenReady: () => Promise<void>;
  on: (event: string, listener: (...args: unknown[]) => void) => void;
  quit: () => void;
  exit?: (exitCode?: number) => void;
};

type IpcMainStub = {
  handle: (channel: string, listener: () => Promise<void> | void) => void;
  on: (channel: string, listener: (event: { returnValue?: unknown }) => void) => void;
};

type WindowStub = {
  loadFile: (filePath: string) => Promise<void>;
  loadURL: (url: string) => Promise<void>;
  show: () => void;
  close: () => void;
  destroy?: () => void;
  isDestroyed?: () => boolean;
  focus: () => void;
  isMinimized: () => boolean;
  restore: () => void;
};

type BackendOwnerStub = {
  origin: string;
  prepareForExit: () => Promise<void>;
  stop: () => Promise<void>;
  exited: Promise<Error | null>;
};

function createDeferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((innerResolve) => {
    resolve = innerResolve;
  });
  return { promise, resolve };
}

function createBackendOwnerStub(
  exited: Promise<Error | null>,
): BackendOwnerStub {
  return {
    origin: "http://127.0.0.1:18600",
    prepareForExit: async () => {},
    stop: async () => {},
    exited,
  };
}

function createWindowStub(overrides: Partial<WindowStub> = {}): WindowStub {
  return {
    loadFile: async () => {},
    loadURL: async () => {},
    show: () => {},
    close: () => {},
    destroy: () => {},
    isDestroyed: () => false,
    focus: () => {},
    isMinimized: () => false,
    restore: () => {},
    ...overrides,
  };
}

function createProductPaths(distributionKind: "installed" | "portable"): ProductPaths {
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), "neo-tts-main-"));
  const runtimeRoot =
    distributionKind === "installed"
      ? path.join(workspace, "NeoTTS")
      : path.join(workspace, "NeoTTS-Portable");
  const resourcesDir = path.join(runtimeRoot, "resources", "app-runtime");
  const userDataDir =
    distributionKind === "installed"
      ? path.join(workspace, "AppData", "Local", "NeoTTS")
      : path.join(runtimeRoot, "data");
  const exportsDir =
    distributionKind === "installed"
      ? path.join(workspace, "Documents", "NeoTTS", "Exports")
      : path.join(runtimeRoot, "exports");

  return {
    distributionKind,
    runtimeRoot,
    resourcesDir,
    backendDir: path.join(resourcesDir, "backend"),
    frontendDir: path.join(resourcesDir, "frontend-dist"),
    gptSovitsDir: path.join(resourcesDir, "GPT_SoVITS"),
    runtimePython: path.join(resourcesDir, "runtime", "python", "python.exe"),
    builtinModelDir: path.join(resourcesDir, "models", "builtin"),
    configDir: path.join(resourcesDir, "config"),
    userDataDir,
    logsDir: path.join(userDataDir, "logs"),
    exportsDir,
    userModelsDir: path.join(userDataDir, "models"),
  };
}

function materializeRuntime(paths: ProductPaths, options?: { includeFrontend?: boolean }) {
  fs.mkdirSync(paths.backendDir, { recursive: true });
  fs.mkdirSync(paths.gptSovitsDir, { recursive: true });
  fs.mkdirSync(paths.builtinModelDir, { recursive: true });
  fs.mkdirSync(paths.configDir, { recursive: true });
  fs.mkdirSync(path.dirname(paths.runtimePython), { recursive: true });
  fs.writeFileSync(paths.runtimePython, "", "utf-8");
  if (paths.distributionKind === "portable") {
    fs.mkdirSync(paths.runtimeRoot, { recursive: true });
    fs.writeFileSync(path.join(paths.runtimeRoot, "portable.flag"), "", "utf-8");
  }
  if (options?.includeFrontend !== false) {
    fs.mkdirSync(paths.frontendDir, { recursive: true });
    fs.writeFileSync(path.join(paths.frontendDir, "index.html"), "<html></html>", "utf-8");
  }
}

describe("desktop main", () => {
  it("product main requests single instance lock before creating the window", async () => {
    const order: string[] = [];
    const app: AppStub = {
      requestSingleInstanceLock: () => {
        order.push("requestSingleInstanceLock");
        return true;
      },
      whenReady: async () => {
        order.push("whenReady");
      },
      on: () => {},
      quit: () => {
        order.push("quit");
      },
    };
    const mainWindow: WindowStub = {
      loadFile: async () => {
        order.push("loadFile");
      },
      loadURL: async () => {
        order.push("loadURL");
      },
      show: () => {
        order.push("show");
      },
      focus: () => {
        order.push("focus");
      },
      isMinimized: () => false,
      restore: () => {
        order.push("restore");
      },
    };

    await runMain({
      app,
      ipcMain: {
        handle: () => {},
        on: () => {},
      },
      projectRoot: "F:/neo-tts",
      startBackend: async () => createBackendOwnerStub(createDeferred<Error | null>().promise),
      createMainWindow: () => {
        order.push("createMainWindow");
        return mainWindow;
      },
    });

    expect(order).toEqual([
      "requestSingleInstanceLock",
      "whenReady",
      "createMainWindow",
      "show",
      "loadFile",
    ]);
  });

  it("dev mode loads frontend/dist via loadFile", async () => {
    let loadedPath = "";
    const app: AppStub = {
      requestSingleInstanceLock: () => true,
      whenReady: async () => {},
      on: () => {},
      quit: () => {},
    };

    await runMain({
      app,
      ipcMain: {
        handle: () => {},
        on: () => {},
      },
      projectRoot: "F:/neo-tts",
      startBackend: async () => createBackendOwnerStub(createDeferred<Error | null>().promise),
      createMainWindow: () => createWindowStub({
        loadFile: async (filePath: string) => {
          loadedPath = filePath;
        },
      }),
    });

    expect(loadedPath).toBe(
      path.join("F:/neo-tts", "frontend", "dist", "index.html"),
    );
  });

  it("second instance focuses existing window instead of creating a new owner", async () => {
    let secondInstanceHandler: (() => void) | undefined;
    let createCalls = 0;
    const focus = vi.fn();
    const restore = vi.fn();
    const app: AppStub = {
      requestSingleInstanceLock: () => true,
      whenReady: async () => {},
      on: (event: string, listener: (...args: unknown[]) => void) => {
        if (event === "second-instance") {
          secondInstanceHandler = () => listener();
        }
      },
      quit: () => {},
    };

    await runMain({
      app,
      ipcMain: {
        handle: () => {},
        on: () => {},
      },
      projectRoot: "F:/neo-tts",
      startBackend: async () => createBackendOwnerStub(createDeferred<Error | null>().promise),
      createMainWindow: () => {
        createCalls += 1;
        return createWindowStub({
          focus,
          isMinimized: () => true,
          restore,
        });
      },
    });

    secondInstanceHandler?.();

    expect(createCalls).toBe(1);
    expect(restore).toHaveBeenCalledOnce();
    expect(focus).toHaveBeenCalledOnce();
  });

  it("second instance shows an existing hidden window before focusing it", async () => {
    let secondInstanceHandler: (() => void) | undefined;
    const show = vi.fn();
    const focus = vi.fn();
    const app: AppStub = {
      requestSingleInstanceLock: () => true,
      whenReady: async () => {},
      on: (event: string, listener: (...args: unknown[]) => void) => {
        if (event === "second-instance") {
          secondInstanceHandler = () => listener();
        }
      },
      quit: () => {},
    };

    await runMain({
      app,
      ipcMain: {
        handle: () => {},
        on: () => {},
      },
      projectRoot: "F:/neo-tts",
      startBackend: async () => createBackendOwnerStub(createDeferred<Error | null>().promise),
      createMainWindow: () =>
        createWindowStub({
          show,
          focus,
        }),
    });

    show.mockClear();
    focus.mockClear();
    secondInstanceHandler?.();

    expect(show).toHaveBeenCalledOnce();
    expect(focus).toHaveBeenCalledOnce();
  });

  it("main starts backend before showing the window", async () => {
    const order: string[] = [];
    const backendExit = createDeferred<Error | null>();
    const app: AppStub = {
      requestSingleInstanceLock: () => {
        order.push("requestSingleInstanceLock");
        return true;
      },
      whenReady: async () => {
        order.push("whenReady");
      },
      on: () => {},
      quit: () => {
        order.push("quit");
      },
    };

    await runMain({
      app,
      ipcMain: {
        handle: () => {},
        on: () => {},
      },
      projectRoot: "F:/neo-tts",
      startBackend: async () => {
        order.push("startBackend");
        return {
          origin: "http://127.0.0.1:18600",
          prepareForExit: async () => {},
          stop: async () => {},
          exited: backendExit.promise,
        };
      },
      createMainWindow: () => {
        order.push("createMainWindow");
        return createWindowStub({
          loadFile: async () => {
            order.push("loadFile");
          },
          loadURL: async () => {
            order.push("loadURL");
          },
          show: () => {
            order.push("show");
          },
        });
      },
    });

    expect(order).toEqual([
      "requestSingleInstanceLock",
      "whenReady",
      "startBackend",
      "createMainWindow",
      "show",
      "loadFile",
    ]);
    backendExit.resolve(null);
  });

  it("renderer exit request makes main call backend prepare-exit and then quit", async () => {
    const order: string[] = [];
    const backendExit = createDeferred<Error | null>();
    let requestExitHandler: (() => Promise<void> | void) | undefined;
    const app: AppStub = {
      requestSingleInstanceLock: () => true,
      whenReady: async () => {},
      on: () => {},
      quit: () => {
        order.push("quit");
      },
    };

    await runMain({
      app,
      ipcMain: {
        handle: (channel: string, listener: () => Promise<void> | void) => {
          if (channel === APP_REQUEST_EXIT_CHANNEL) {
            requestExitHandler = listener;
          }
        },
        on: () => {},
      },
      projectRoot: "F:/neo-tts",
      startBackend: async () => ({
        origin: "http://127.0.0.1:18600",
        prepareForExit: async () => {
          order.push("prepareForExit");
        },
        stop: async () => {
          order.push("stopBackend");
        },
        exited: backendExit.promise,
      }),
      createMainWindow: () =>
        createWindowStub({
          close: () => {
            order.push("closeWindow");
          },
        }),
    });

    expect(requestExitHandler).toBeTypeOf("function");
    await requestExitHandler?.();

    expect(order).toEqual(["prepareForExit", "stopBackend", "closeWindow", "quit"]);
    backendExit.resolve(null);
  });

  it("renderer exit still stops backend and quits when prepare-exit fails", async () => {
    const order: string[] = [];
    const backendExit = createDeferred<Error | null>();
    let requestExitHandler: (() => Promise<void> | void) | undefined;
    const app: AppStub = {
      requestSingleInstanceLock: () => true,
      whenReady: async () => {},
      on: () => {},
      quit: () => {
        order.push("quit");
      },
    };

    await runMain({
      app,
      ipcMain: {
        handle: (channel: string, listener: () => Promise<void> | void) => {
          if (channel === APP_REQUEST_EXIT_CHANNEL) {
            requestExitHandler = listener;
          }
        },
        on: () => {},
      },
      projectRoot: "F:/neo-tts",
      startBackend: async () => ({
        origin: "http://127.0.0.1:18600",
        prepareForExit: async () => {
          order.push("prepareForExit");
          throw new Error("backend prepare-exit returned 500");
        },
        stop: async () => {
          order.push("stopBackend");
        },
        exited: backendExit.promise,
      }),
      createMainWindow: () =>
        createWindowStub({
          close: () => {
            order.push("closeWindow");
          },
        }),
    });

    await expect(requestExitHandler?.()).resolves.toBeUndefined();

    expect(order).toEqual(["prepareForExit", "stopBackend", "closeWindow", "quit"]);
    backendExit.resolve(null);
  });

  it("renderer exit force-closes the window when app.quit does not finish in time", async () => {
    vi.useFakeTimers();
    const backendExit = createDeferred<Error | null>();
    let requestExitHandler: (() => Promise<void> | void) | undefined;
    const quit = vi.fn();
    const exit = vi.fn();
    const destroy = vi.fn();

    await runMain({
      app: {
        requestSingleInstanceLock: () => true,
        whenReady: async () => {},
        on: () => {},
        quit,
        exit,
      },
      ipcMain: {
        handle: (channel: string, listener: () => Promise<void> | void) => {
          if (channel === APP_REQUEST_EXIT_CHANNEL) {
            requestExitHandler = listener;
          }
        },
        on: () => {},
      },
      projectRoot: "F:/neo-tts",
      startBackend: async () => ({
        origin: "http://127.0.0.1:18600",
        prepareForExit: async () => {},
        stop: async () => {},
        exited: backendExit.promise,
      }),
      createMainWindow: () =>
        createWindowStub({
          destroy,
          isDestroyed: () => false,
        }),
    });

    await requestExitHandler?.();
    expect(quit).toHaveBeenCalledOnce();
    expect(exit).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1_500);

    expect(destroy).toHaveBeenCalledOnce();
    expect(exit).toHaveBeenCalledWith(0);
    vi.useRealTimers();
    backendExit.resolve(null);
  });

  it("renderer can ask main process to open external links in the default browser", async () => {
    let openExternalHandler:
      | ((...args: unknown[]) => Promise<void> | void)
      | undefined;
    const openExternal = vi.fn().mockResolvedValue(undefined);

    await runMain({
      app: {
        requestSingleInstanceLock: () => true,
        whenReady: async () => {},
        on: () => {},
        quit: () => {},
      },
      ipcMain: {
        handle: (channel: string, listener: (...args: unknown[]) => Promise<void> | void) => {
          if (channel === APP_OPEN_EXTERNAL_URL_CHANNEL) {
            openExternalHandler = listener;
          }
        },
        on: () => {},
      },
      projectRoot: "F:/neo-tts",
      startBackend: async () => createBackendOwnerStub(createDeferred<Error | null>().promise),
      createMainWindow: () => createWindowStub(),
      openExternalUrl: openExternal,
    });

    await openExternalHandler?.({} as never, "https://github.com/CommentOut64/neo-tts");

    expect(openExternal).toHaveBeenCalledWith("https://github.com/CommentOut64/neo-tts");
  });

  it("backend exit moves the app into fatal state instead of silently hanging", async () => {
    const backendExit = createDeferred<Error | null>();
    const quit = vi.fn();
    const onFatalState = vi.fn();
    const app: AppStub = {
      requestSingleInstanceLock: () => true,
      whenReady: async () => {},
      on: () => {},
      quit,
    };

    await runMain({
      app,
      ipcMain: {
        handle: () => {},
        on: () => {},
      },
      projectRoot: "F:/neo-tts",
      startBackend: async () => ({
        origin: "http://127.0.0.1:18600",
        prepareForExit: async () => {},
        stop: async () => {},
        exited: backendExit.promise,
      }),
      createMainWindow: () => createWindowStub(),
      onFatalState,
    });

    const exitError = new Error("backend exited unexpectedly");
    backendExit.resolve(exitError);
    await Promise.resolve();
    await Promise.resolve();

    expect(onFatalState).toHaveBeenCalledOnce();
    expect(onFatalState).toHaveBeenCalledWith(
      expect.objectContaining({
        reason: "backend-exit",
        error: exitError,
      }),
    );
    expect(quit).toHaveBeenCalledOnce();
  });

  it("starts installed flavor backend with appdata paths", async () => {
    const productPaths = createProductPaths("installed");
    materializeRuntime(productPaths);
    let receivedOptions: unknown;

    await runMain({
      app: {
        requestSingleInstanceLock: () => true,
        whenReady: async () => {},
        on: () => {},
        quit: () => {},
      },
      ipcMain: {
        handle: () => {},
        on: () => {},
      },
      projectRoot: productPaths.runtimeRoot,
      productPaths,
      startBackend: async (options) => {
        receivedOptions = options;
        return createBackendOwnerStub(createDeferred<Error | null>().promise);
      },
      createMainWindow: () => createWindowStub(),
    });

    expect(receivedOptions).toEqual(
      expect.objectContaining({
        pythonExecutable: productPaths.runtimePython,
        workingDirectory: productPaths.resourcesDir,
        onLogLine: expect.any(Function),
        environment: expect.objectContaining({
          NEO_TTS_DISTRIBUTION_KIND: "installed",
          NEO_TTS_USER_DATA_ROOT: productPaths.userDataDir,
          NEO_TTS_EXPORTS_ROOT: productPaths.exportsDir,
        }),
      }),
    );
  });

  it("starts portable flavor backend with side-by-side data paths", async () => {
    const productPaths = createProductPaths("portable");
    materializeRuntime(productPaths);
    let receivedOptions: unknown;

    await runMain({
      app: {
        requestSingleInstanceLock: () => true,
        whenReady: async () => {},
        on: () => {},
        quit: () => {},
      },
      ipcMain: {
        handle: () => {},
        on: () => {},
      },
      projectRoot: productPaths.runtimeRoot,
      productPaths,
      startBackend: async (options) => {
        receivedOptions = options;
        return createBackendOwnerStub(createDeferred<Error | null>().promise);
      },
      createMainWindow: () => createWindowStub(),
    });

    expect(receivedOptions).toEqual(
      expect.objectContaining({
        onLogLine: expect.any(Function),
        environment: expect.objectContaining({
          NEO_TTS_DISTRIBUTION_KIND: "portable",
          NEO_TTS_USER_DATA_ROOT: productPaths.userDataDir,
          NEO_TTS_EXPORTS_ROOT: productPaths.exportsDir,
        }),
      }),
    );
  });

  it("reports fatal state when frontend dist is missing", async () => {
    const productPaths = createProductPaths("installed");
    materializeRuntime(productPaths, { includeFrontend: false });
    const quit = vi.fn();
    const onFatalState = vi.fn();
    const startBackend = vi.fn();

    await runMain({
      app: {
        requestSingleInstanceLock: () => true,
        whenReady: async () => {},
        on: () => {},
        quit,
      },
      ipcMain: {
        handle: () => {},
        on: () => {},
      },
      projectRoot: productPaths.runtimeRoot,
      productPaths,
      startBackend,
      createMainWindow: () => createWindowStub(),
      onFatalState,
    });

    expect(startBackend).not.toHaveBeenCalled();
    expect(onFatalState).toHaveBeenCalledWith(
      expect.objectContaining({
        reason: "invalid-runtime",
      }),
    );
    expect(quit).toHaveBeenCalledOnce();
  });

  it("production mode loads frontend via loadURL from backend origin", async () => {
    const productPaths = createProductPaths("installed");
    materializeRuntime(productPaths);
    let loadedURL = "";
    let loadFileCalled = false;

    await runMain({
      app: {
        requestSingleInstanceLock: () => true,
        whenReady: async () => {},
        on: () => {},
        quit: () => {},
      },
      ipcMain: {
        handle: () => {},
        on: () => {},
      },
      projectRoot: productPaths.runtimeRoot,
      productPaths,
      startBackend: async () => createBackendOwnerStub(createDeferred<Error | null>().promise),
      createMainWindow: () => createWindowStub({
        loadFile: async () => {
          loadFileCalled = true;
        },
        loadURL: async (url: string) => {
          loadedURL = url;
        },
      }),
    });

    expect(loadFileCalled).toBe(false);
    expect(loadedURL).toBe("http://127.0.0.1:18600");
  });

  it("bridges backend stdout/stderr lines into runtime logger", async () => {
    const logger = {
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
    };

    await runMain({
      app: {
        requestSingleInstanceLock: () => true,
        whenReady: async () => {},
        on: () => {},
        quit: () => {},
      },
      ipcMain: {
        handle: () => {},
        on: () => {},
      },
      projectRoot: "F:/neo-tts",
      runtimeLogger: logger,
      startBackend: async (options) => {
        options.onLogLine?.("stderr", "backend log line");
        return createBackendOwnerStub(createDeferred<Error | null>().promise);
      },
      createMainWindow: () => createWindowStub(),
    });

    expect(logger.info).toHaveBeenCalledWith("[backend:stderr] backend log line");
  });
});
