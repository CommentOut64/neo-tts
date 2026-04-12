import path from "node:path";
import { describe, expect, it, vi } from "vitest";

import { APP_REQUEST_EXIT_CHANNEL } from "../src/ipc/channels";
import { runMain } from "../src/main";

type AppStub = {
  requestSingleInstanceLock: () => boolean;
  whenReady: () => Promise<void>;
  on: (event: string, listener: (...args: unknown[]) => void) => void;
  quit: () => void;
};

type IpcMainStub = {
  handle: (channel: string, listener: () => Promise<void> | void) => void;
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
});
