import path from "node:path";
import fs from "node:fs";
import os from "node:os";
import { describe, expect, it, vi } from "vitest";

import { APP_REQUEST_EXIT_CHANNEL } from "../src/ipc/channels";
import { runMain } from "../src/main";
import type { ProductPaths } from "../src/runtime/paths";

type AppStub = {
  requestSingleInstanceLock: () => boolean;
  whenReady: () => Promise<void>;
  on: (event: string, listener: (...args: unknown[]) => void) => void;
  quit: () => void;
};

type IpcMainStub = {
  handle: (channel: string, listener: () => Promise<void> | void) => void;
  on: (channel: string, listener: (event: { returnValue?: unknown }) => void) => void;
};

type WindowStub = {
  loadFile: (filePath: string) => Promise<void>;
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
      "loadFile",
    ]);
  });

  it("main loads frontend/dist in production mode", async () => {
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
      createMainWindow: () => ({
        loadFile: async (filePath: string) => {
          loadedPath = filePath;
        },
        focus: () => {},
        isMinimized: () => false,
        restore: () => {},
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
        return {
          loadFile: async () => {},
          focus,
          isMinimized: () => true,
          restore,
        };
      },
    });

    secondInstanceHandler?.();

    expect(createCalls).toBe(1);
    expect(restore).toHaveBeenCalledOnce();
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
        return {
          loadFile: async () => {
            order.push("loadFile");
          },
          focus: () => {},
          isMinimized: () => false,
          restore: () => {},
        };
      },
    });

    expect(order).toEqual([
      "requestSingleInstanceLock",
      "whenReady",
      "startBackend",
      "createMainWindow",
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
      createMainWindow: () => ({
        loadFile: async () => {},
        focus: () => {},
        isMinimized: () => false,
        restore: () => {},
      }),
    });

    expect(requestExitHandler).toBeTypeOf("function");
    await requestExitHandler?.();

    expect(order).toEqual(["prepareForExit", "stopBackend", "quit"]);
    backendExit.resolve(null);
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
      createMainWindow: () => ({
        loadFile: async () => {},
        focus: () => {},
        isMinimized: () => false,
        restore: () => {},
      }),
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
      createMainWindow: () => ({
        loadFile: async () => {},
        focus: () => {},
        isMinimized: () => false,
        restore: () => {},
      }),
    });

    expect(receivedOptions).toEqual(
      expect.objectContaining({
        pythonExecutable: productPaths.runtimePython,
        workingDirectory: productPaths.resourcesDir,
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
      createMainWindow: () => ({
        loadFile: async () => {},
        focus: () => {},
        isMinimized: () => false,
        restore: () => {},
      }),
    });

    expect(receivedOptions).toEqual(
      expect.objectContaining({
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
      createMainWindow: () => ({
        loadFile: async () => {},
        focus: () => {},
        isMinimized: () => false,
        restore: () => {},
      }),
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
});
