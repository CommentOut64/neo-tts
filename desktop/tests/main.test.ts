import path from "node:path";
import fs from "node:fs";
import os from "node:os";
import { describe, expect, it, vi } from "vitest";

import {
  APP_CHECK_UPDATE_CHANNEL,
  APP_OPEN_EXTERNAL_URL_CHANNEL,
  APP_REQUEST_EXIT_CHANNEL,
  APP_RESTART_AND_APPLY_UPDATE_CHANNEL,
  APP_START_UPDATE_DOWNLOAD_CHANNEL,
} from "../src/ipc/channels";
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
  handle: (channel: string, listener: (...args: unknown[]) => Promise<unknown> | unknown) => void;
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

type BootstrapControlClientStub = {
  apiVersion: string;
  bootstrapVersion: string;
  sessionId: string;
  checkForUpdate: (...args: unknown[]) => Promise<unknown>;
  downloadUpdate: (...args: unknown[]) => Promise<unknown>;
  restartAndApplyUpdate: (...args: unknown[]) => Promise<unknown>;
  reportSessionReady: (...args: unknown[]) => Promise<unknown>;
  reportSessionFailed: (...args: unknown[]) => Promise<unknown>;
  reportRestartForUpdate: (...args: unknown[]) => Promise<unknown>;
};

type ProductPathsWithRoot = ProductPaths & {
  productRoot: string;
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

function createProductPaths(distributionKind: "installed" | "portable"): ProductPathsWithRoot {
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), "neo-tts-main-"));
  const productRoot =
    distributionKind === "installed"
      ? path.join(workspace, "NeoTTS")
      : path.join(workspace, "NeoTTS-Portable");
  const bootstrapRoot = path.join(productRoot, "packages", "bootstrap", "1.1.0");
  const updateAgentRoot = path.join(productRoot, "packages", "update-agent", "1.1.0");
  const shellRoot = path.join(productRoot, "packages", "shell", "v0.0.1");
  const appCoreRoot = path.join(productRoot, "packages", "app-core", "v0.0.1");
  const runtimeLayerRoot = path.join(productRoot, "packages", "runtime", "py311-cu128-v1");
  const modelsRoot = path.join(productRoot, "packages", "models", "builtin-v1");
  const pretrainedModelsRoot = path.join(productRoot, "packages", "pretrained-models", "support-v1");
  const userDataDir =
    distributionKind === "installed"
      ? path.join(workspace, "AppData", "Local", "NeoTTS")
      : path.join(productRoot, "data");
  const exportsDir =
    distributionKind === "installed"
      ? path.join(workspace, "Documents", "NeoTTS", "Exports")
      : path.join(productRoot, "exports");

  return {
    resolutionKind: "descriptor",
    runtimeDescriptorPath: path.join(productRoot, "state", "current.json"),
    distributionKind,
    productRoot,
    bootstrapRoot,
    updateAgentRoot,
    shellRoot,
    appCoreRoot,
    runtimeRoot: runtimeLayerRoot,
    modelsRoot,
    pretrainedModelsRoot,
    resourcesDir: appCoreRoot,
    backendDir: path.join(appCoreRoot, "backend"),
    frontendDir: path.join(appCoreRoot, "frontend-dist"),
    gptSovitsDir: path.join(appCoreRoot, "GPT_SoVITS"),
    runtimePython: path.join(runtimeLayerRoot, "runtime", "python", "python.exe"),
    builtinModelDir: path.join(modelsRoot, "models", "builtin"),
    pretrainedModelsDir: path.join(pretrainedModelsRoot, "pretrained_models"),
    configDir: path.join(appCoreRoot, "config"),
    userDataDir,
    logsDir: path.join(userDataDir, "logs"),
    exportsDir,
    userModelsDir: path.join(userDataDir, "models"),
  };
}

function materializeRuntime(
  paths: ProductPathsWithRoot,
  options?: {
    includeFrontend?: boolean;
    includeShell?: boolean;
    includePretrainedModels?: boolean;
    includeSvModel?: boolean;
  },
) {
  fs.mkdirSync(paths.backendDir, { recursive: true });
  fs.mkdirSync(paths.gptSovitsDir, { recursive: true });
  fs.mkdirSync(paths.builtinModelDir, { recursive: true });
  fs.mkdirSync(paths.pretrainedModelsDir, { recursive: true });
  fs.mkdirSync(paths.configDir, { recursive: true });
  fs.mkdirSync(path.dirname(paths.runtimePython), { recursive: true });
  fs.writeFileSync(paths.runtimePython, "", "utf-8");
  fs.mkdirSync(path.join(paths.builtinModelDir, "chinese-hubert-base"), { recursive: true });
  fs.writeFileSync(path.join(paths.builtinModelDir, "chinese-hubert-base", "config.json"), "{}", "utf-8");
  fs.writeFileSync(path.join(paths.builtinModelDir, "chinese-hubert-base", "preprocessor_config.json"), "{}", "utf-8");
  fs.writeFileSync(path.join(paths.builtinModelDir, "chinese-hubert-base", "pytorch_model.bin"), "", "utf-8");
  fs.mkdirSync(path.join(paths.builtinModelDir, "chinese-roberta-wwm-ext-large"), { recursive: true });
  fs.writeFileSync(path.join(paths.builtinModelDir, "chinese-roberta-wwm-ext-large", "config.json"), "{}", "utf-8");
  fs.writeFileSync(path.join(paths.builtinModelDir, "chinese-roberta-wwm-ext-large", "pytorch_model.bin"), "", "utf-8");
  fs.writeFileSync(path.join(paths.builtinModelDir, "chinese-roberta-wwm-ext-large", "tokenizer.json"), "{}", "utf-8");
  fs.mkdirSync(path.join(paths.builtinModelDir, "neuro2"), { recursive: true });
  fs.writeFileSync(path.join(paths.builtinModelDir, "neuro2", "neuro2-e4.ckpt"), "", "utf-8");
  fs.writeFileSync(path.join(paths.builtinModelDir, "neuro2", "neuro2_e4_s424.pth"), "", "utf-8");
  fs.writeFileSync(path.join(paths.builtinModelDir, "neuro2", "audio1.wav"), "", "utf-8");
  fs.mkdirSync(path.join(paths.pretrainedModelsDir, "sv"), { recursive: true });
  if (options?.includeSvModel !== false) {
    fs.writeFileSync(
      path.join(paths.pretrainedModelsDir, "sv", "pretrained_eres2netv2w24s4ep4.ckpt"),
      "",
      "utf-8",
    );
  }
  fs.mkdirSync(path.join(paths.pretrainedModelsDir, "fast_langdetect"), { recursive: true });
  fs.writeFileSync(path.join(paths.pretrainedModelsDir, "fast_langdetect", "lid.176.bin"), "", "utf-8");
  fs.writeFileSync(
    path.join(paths.configDir, "voices.json"),
    JSON.stringify({
      neuro2: {
        gpt_path: "models/builtin/neuro2/neuro2-e4.ckpt",
        sovits_path: "models/builtin/neuro2/neuro2_e4_s424.pth",
        ref_audio: "models/builtin/neuro2/audio1.wav",
      },
    }),
    "utf-8",
  );
  if (paths.distributionKind === "portable") {
    fs.mkdirSync(paths.productRoot, { recursive: true });
    fs.writeFileSync(path.join(paths.productRoot, "portable.flag"), "", "utf-8");
  }
  if (options?.includeShell !== false) {
    fs.mkdirSync(paths.shellRoot, { recursive: true });
    fs.writeFileSync(path.join(paths.shellRoot, "NeoTTSApp.exe"), "", "utf-8");
  }
  if (options?.includePretrainedModels === false) {
    fs.rmSync(paths.pretrainedModelsDir, { recursive: true, force: true });
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

  it("registers update IPC handlers that delegate to bootstrap control client", async () => {
    const handled = new Map<string, (...args: unknown[]) => Promise<unknown> | unknown>();
    const order: string[] = [];
    const bootstrapClient: BootstrapControlClientStub = {
      apiVersion: "v1",
      bootstrapVersion: "1.1.0",
      sessionId: "session-1",
      checkForUpdate: vi.fn().mockResolvedValue({ status: "update-available" }),
      downloadUpdate: vi.fn().mockResolvedValue({ status: "ready-to-restart" }),
      restartAndApplyUpdate: vi.fn().mockResolvedValue({ status: "switching" }),
      reportSessionReady: vi.fn().mockResolvedValue(undefined),
      reportSessionFailed: vi.fn().mockResolvedValue(undefined),
      reportRestartForUpdate: vi.fn().mockResolvedValue({ status: "restart-requested" }),
    };

    await runMain({
      ipcMain: {
        handle: (channel, listener) => {
          handled.set(channel, listener);
        },
        on: () => {},
      },
      projectRoot: "F:/neo-tts",
      productPaths: (() => {
        const paths = createProductPaths("installed");
        materializeRuntime(paths);
        return paths;
      })(),
      environment: {
        NEO_TTS_BOOTSTRAP_CONTROL_ORIGIN: "http://127.0.0.1:19090",
        NEO_TTS_BOOTSTRAP_API_VERSION: "v1",
      },
      createBootstrapClient: async () => bootstrapClient,
      startBackend: async () => ({
        origin: "http://127.0.0.1:18600",
        prepareForExit: async () => {
          order.push("prepareForExit");
        },
        stop: async () => {
          order.push("stopBackend");
        },
        exited: createDeferred<Error | null>().promise,
      }),
      createMainWindow: () =>
        createWindowStub({
          close: () => {
            order.push("closeWindow");
          },
        }),
      app: {
        requestSingleInstanceLock: () => true,
        whenReady: async () => {},
        on: () => {},
        quit: () => {
          order.push("quit");
        },
      },
    });

    await expect(handled.get(APP_CHECK_UPDATE_CHANNEL)?.({}, { channel: "stable", automatic: false })).resolves.toEqual({
      status: "update-available",
    });
    await expect(handled.get(APP_START_UPDATE_DOWNLOAD_CHANNEL)?.({}, { releaseId: "v0.0.2" })).resolves.toEqual({
      status: "ready-to-restart",
    });
    await expect(handled.get(APP_RESTART_AND_APPLY_UPDATE_CHANNEL)?.({}, { releaseId: "v0.0.2" })).resolves.toEqual({
      status: "switching",
    });

    expect(bootstrapClient.checkForUpdate).toHaveBeenCalledWith({ channel: "stable", automatic: false });
    expect(bootstrapClient.downloadUpdate).toHaveBeenCalledWith({ releaseId: "v0.0.2" });
    expect(bootstrapClient.restartAndApplyUpdate).toHaveBeenCalledWith({ releaseId: "v0.0.2" });
    expect(bootstrapClient.reportRestartForUpdate).toHaveBeenCalledWith({ sessionId: "session-1" });
    expect(order).toEqual(["prepareForExit", "stopBackend", "closeWindow", "quit"]);
  });

  it("reports session-ready to bootstrap after packaged renderer load succeeds", async () => {
    const reportSessionReady = vi.fn().mockResolvedValue(undefined);
    const productPaths = createProductPaths("portable");
    materializeRuntime(productPaths);

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
      projectRoot: productPaths.productRoot,
      productPaths,
      environment: {
        NEO_TTS_BOOTSTRAP_CONTROL_ORIGIN: "http://127.0.0.1:19090",
        NEO_TTS_BOOTSTRAP_API_VERSION: "v1",
      },
      createBootstrapClient: async () => ({
        apiVersion: "v1",
        bootstrapVersion: "1.1.0",
        sessionId: "session-1",
        checkForUpdate: vi.fn(),
        downloadUpdate: vi.fn(),
        restartAndApplyUpdate: vi.fn(),
        reportSessionReady,
        reportSessionFailed: vi.fn(),
        reportRestartForUpdate: vi.fn(),
      }),
      startBackend: async () => createBackendOwnerStub(createDeferred<Error | null>().promise),
      createMainWindow: () => createWindowStub(),
    });

    expect(reportSessionReady).toHaveBeenCalledWith({ sessionId: "session-1" });
  });

  it("reports startup-failed to bootstrap when backend startup fails", async () => {
    const reportSessionFailed = vi.fn().mockResolvedValue(undefined);
    const productPaths = createProductPaths("installed");
    materializeRuntime(productPaths);

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
      projectRoot: productPaths.productRoot,
      productPaths,
      environment: {
        NEO_TTS_BOOTSTRAP_CONTROL_ORIGIN: "http://127.0.0.1:19090",
        NEO_TTS_BOOTSTRAP_API_VERSION: "v1",
      },
      createBootstrapClient: async () => ({
        apiVersion: "v1",
        bootstrapVersion: "1.1.0",
        sessionId: "session-1",
        checkForUpdate: vi.fn(),
        downloadUpdate: vi.fn(),
        restartAndApplyUpdate: vi.fn(),
        reportSessionReady: vi.fn(),
        reportSessionFailed,
        reportRestartForUpdate: vi.fn(),
      }),
      startBackend: async () => {
        throw new Error("backend health check timed out");
      },
      createMainWindow: () => createWindowStub(),
    });

    expect(reportSessionFailed).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "session-1",
        code: "startup-failed",
      }),
    );
  });

  it("reports backend-exit to bootstrap when backend exits unexpectedly", async () => {
    const backendExit = createDeferred<Error | null>();
    const reportSessionFailed = vi.fn().mockResolvedValue(undefined);

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
      environment: {
        NEO_TTS_BOOTSTRAP_CONTROL_ORIGIN: "http://127.0.0.1:19090",
        NEO_TTS_BOOTSTRAP_API_VERSION: "v1",
      },
      createBootstrapClient: async () => ({
        apiVersion: "v1",
        bootstrapVersion: "1.1.0",
        sessionId: "session-1",
        checkForUpdate: vi.fn(),
        downloadUpdate: vi.fn(),
        restartAndApplyUpdate: vi.fn(),
        reportSessionReady: vi.fn(),
        reportSessionFailed,
        reportRestartForUpdate: vi.fn(),
      }),
      startBackend: async () => ({
        origin: "http://127.0.0.1:18600",
        prepareForExit: async () => {},
        stop: async () => {},
        exited: backendExit.promise,
      }),
      createMainWindow: () => createWindowStub(),
    });

    backendExit.resolve(new Error("backend exited unexpectedly"));
    await Promise.resolve();
    await Promise.resolve();

    expect(reportSessionFailed).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "session-1",
        code: "backend-exit",
      }),
    );
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
      projectRoot: productPaths.bootstrapRoot,
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
      projectRoot: productPaths.bootstrapRoot,
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
          NEO_TTS_PROJECT_ROOT: productPaths.productRoot,
          NEO_TTS_USER_DATA_ROOT: productPaths.userDataDir,
          NEO_TTS_EXPORTS_ROOT: productPaths.exportsDir,
        }),
      }),
    );
  });

  it("portable runtime validation reads portable.flag from product root instead of bootstrap package root", async () => {
    const productPaths = createProductPaths("portable");
    materializeRuntime(productPaths);
    const quit = vi.fn();
    const onFatalState = vi.fn();
    const startBackend = vi.fn().mockResolvedValue(
      createBackendOwnerStub(createDeferred<Error | null>().promise),
    );

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
      projectRoot: productPaths.productRoot,
      productPaths,
      startBackend,
      createMainWindow: () => createWindowStub(),
      onFatalState,
    });

    expect(startBackend).toHaveBeenCalledOnce();
    expect(onFatalState).not.toHaveBeenCalled();
    expect(quit).not.toHaveBeenCalled();
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
      projectRoot: productPaths.bootstrapRoot,
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

  it("reports fatal state when pretrained-models layer is missing", async () => {
    const productPaths = createProductPaths("installed");
    materializeRuntime(productPaths, { includePretrainedModels: false });
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
      projectRoot: productPaths.bootstrapRoot,
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

  it("reports fatal state when packaged support model files are missing", async () => {
    const productPaths = createProductPaths("installed");
    materializeRuntime(productPaths, { includeSvModel: false });
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
      projectRoot: productPaths.bootstrapRoot,
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
      projectRoot: productPaths.bootstrapRoot,
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

  it("production mode clears renderer cache before loading frontend via loadURL", async () => {
    const productPaths = createProductPaths("portable");
    materializeRuntime(productPaths);
    const order: string[] = [];

    await runMain({
      app: {
        requestSingleInstanceLock: () => true,
        whenReady: async () => {
          order.push("whenReady");
        },
        on: () => {},
        quit: () => {},
      },
      ipcMain: {
        handle: () => {},
        on: () => {},
      },
      projectRoot: productPaths.bootstrapRoot,
      productPaths,
      startBackend: async () => {
        order.push("startBackend");
        return createBackendOwnerStub(createDeferred<Error | null>().promise);
      },
      clearRendererCache: async () => {
        order.push("clearRendererCache");
      },
      createMainWindow: () =>
        createWindowStub({
          show: () => {
            order.push("show");
          },
          loadURL: async () => {
            order.push("loadURL");
          },
        }),
    });

    expect(order).toEqual([
      "whenReady",
      "startBackend",
      "clearRendererCache",
      "show",
      "loadURL",
    ]);
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

  it("bridges backend process monitor samples into runtime logger", async () => {
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
        options.onMonitorSample?.({
          pid: 2468,
          cpuSeconds: 12.5,
          workingSetMb: 256,
          threadCount: 9,
          gpuMemoryMb: 1024,
          sampledAt: "2026-04-19T04:00:00.000Z",
        });
        return createBackendOwnerStub(createDeferred<Error | null>().promise);
      },
      createMainWindow: () => createWindowStub(),
    });

    expect(logger.info).toHaveBeenCalledWith(
      "[backend:monitor] pid=2468 rss_mb=256.0 cpu_s=12.5 threads=9 gpu_mb=1024 sampled_at=2026-04-19T04:00:00.000Z",
    );
  });

  it("does not register the legacy renderer diagnostic IPC channel", async () => {
    const handledChannels: string[] = [];

    await runMain({
      app: {
        requestSingleInstanceLock: () => true,
        whenReady: async () => {},
        on: () => {},
        quit: () => {},
      },
      ipcMain: {
        handle: (channel) => {
          handledChannels.push(channel);
        },
        on: () => {},
      },
      projectRoot: "F:/neo-tts",
      runtimeLogger: {
        info: vi.fn(),
        warn: vi.fn(),
        error: vi.fn(),
      },
      startBackend: async () => createBackendOwnerStub(createDeferred<Error | null>().promise),
      createMainWindow: () => createWindowStub(),
    });

    expect(handledChannels).not.toContain("app:renderer-log");
  });
});
