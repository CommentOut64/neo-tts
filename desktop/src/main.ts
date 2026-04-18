import path from "node:path";
import fs from "node:fs";
import os from "node:os";

import type { BackendOwner, StartBackendProcessOptions } from "./backend/process";
import { buildDefaultBackendOptions, startBackendProcess } from "./backend/process";
import {
	APP_GET_RUNTIME_INFO_CHANNEL,
	APP_OPEN_EXTERNAL_URL_CHANNEL,
	APP_REQUEST_EXIT_CHANNEL,
} from "./ipc/channels";
import { buildElectronRuntimeInfo } from "./ipc/runtimeInfo";
import { createCompositeRuntimeLogger, createFileRuntimeLogger, createNoopRuntimeLogger, type RuntimeLogger } from "./logging/runtimeLogger";
import { buildDefaultProductPaths, type DistributionKind, type ProductPaths } from "./runtime/paths";

export interface ElectronAppLike {
	requestSingleInstanceLock(): boolean;
	whenReady(): Promise<void>;
	on(event: string, listener: (...args: unknown[]) => void): void;
	quit(): void;
	exit?(exitCode?: number): void;
	getVersion?(): string;
}

export interface MainWindowLike {
	loadFile(filePath: string): Promise<void> | void;
	loadURL(url: string): Promise<void> | void;
	show(): void;
	close?(): void;
	destroy?(): void;
	isDestroyed?(): boolean;
	focus(): void;
	isMinimized(): boolean;
	restore(): void;
}

export interface IpcMainLike {
	handle(channel: string, listener: (...args: unknown[]) => Promise<void> | void): void;
	on(
		channel: string,
		listener: (event: { returnValue?: unknown }, ...args: unknown[]) => void,
	): void;
}

export interface FatalState {
	reason: "backend-exit" | "invalid-runtime" | "startup-failed";
	error: Error | null;
}

export interface RunMainOptions {
	app: ElectronAppLike;
	ipcMain: IpcMainLike;
	projectRoot: string;
	productPaths?: ProductPaths;
	distributionKind?: DistributionKind;
	startBackend: (options: StartBackendProcessOptions) => Promise<BackendOwner>;
	createMainWindow: () => MainWindowLike;
	clearRendererCache?: () => Promise<void> | void;
	openExternalUrl?: (url: string) => Promise<void> | void;
	runtimeLogger?: RuntimeLogger;
	onFatalState?: (state: FatalState) => void;
}

function closeMainWindow(mainWindow: MainWindowLike | undefined, logger: RuntimeLogger) {
	try {
		mainWindow?.close?.();
	} catch (error) {
		logger.error(
			`main window close failed during shutdown: ${
				error instanceof Error ? error.message : String(error)
			}`,
		);
	}
}

function destroyMainWindow(mainWindow: MainWindowLike | undefined, logger: RuntimeLogger) {
	try {
		if (mainWindow?.isDestroyed?.()) {
			return;
		}
		mainWindow?.destroy?.();
	} catch (error) {
		logger.error(
			`main window destroy failed during forced shutdown: ${
				error instanceof Error ? error.message : String(error)
			}`,
		);
	}
}

function normalizeDisplayVersion(appVersion: string): string {
	const normalized = appVersion.trim().replace(/^v/i, "");
	const baseVersion = normalized.split("-", 1)[0]?.trim() ?? "";
	return baseVersion.length > 0 ? baseVersion : "0.0.1";
}

function resolveAppVersion(app: ElectronAppLike): string {
	try {
		const versionFromApp = app.getVersion?.().trim();
		if (versionFromApp) {
			return versionFromApp;
		}
	} catch {
		// Electron app.getVersion() 在某些测试桩下不存在，继续走 package.json 回退。
	}

	try {
		const packageJsonPath = path.resolve(__dirname, "..", "package.json");
		const raw = fs.readFileSync(packageJsonPath, "utf-8");
		const parsed = JSON.parse(raw) as { version?: string };
		if (typeof parsed.version === "string" && parsed.version.trim().length > 0) {
			return parsed.version.trim();
		}
	} catch {
		// 打包或测试环境下若 package.json 不可读，则回退到稳定展示版本。
	}

	return "0.0.1";
}

export function resolveRendererEntry(
	projectRoot: string,
): string {
	return path.join(projectRoot, "frontend", "dist", "index.html");
}

function validateProductPaths(productPaths: ProductPaths): Error | null {
	const requiredTargets: Array<{ path: string; label: string }> = [
		{ path: productPaths.runtimePython, label: "bundled python" },
		{ path: productPaths.backendDir, label: "backend dir" },
		{ path: productPaths.frontendDir, label: "frontend dist dir" },
		{ path: path.join(productPaths.frontendDir, "index.html"), label: "frontend index.html" },
		{ path: productPaths.gptSovitsDir, label: "GPT_SoVITS dir" },
		{ path: productPaths.builtinModelDir, label: "builtin model dir" },
		{ path: productPaths.configDir, label: "config dir" },
	];
	if (productPaths.distributionKind === "portable") {
		requiredTargets.push({
			path: path.join(productPaths.runtimeRoot, "portable.flag"),
			label: "portable.flag",
		});
	}

	const missing = requiredTargets.filter((target) => !fs.existsSync(target.path));
	if (missing.length === 0) {
		return null;
	}

	return new Error(
		`Product runtime validation failed: ${missing
			.map((target) => `${target.label} (${target.path})`)
			.join(", ")}`,
	);
}

export async function runMain(options: RunMainOptions): Promise<void> {
	const logger = options.runtimeLogger ?? createNoopRuntimeLogger();
	logger.info("electron main entering runMain");

	if (!options.app.requestSingleInstanceLock()) {
		logger.warn("single instance lock denied, quitting");
		options.app.quit();
		return;
	}

	let mainWindow: MainWindowLike | undefined;
	let shuttingDown = false;
	let forceExitTimer: ReturnType<typeof globalThis.setTimeout> | null = null;
	const requestAppShutdown = () => {
		closeMainWindow(mainWindow, logger);
		options.app.quit();
		if (forceExitTimer !== null) {
			return;
		}
		forceExitTimer = globalThis.setTimeout(() => {
			forceExitTimer = null;
			logger.warn("app quit timeout elapsed, forcing window destroy and app exit");
			destroyMainWindow(mainWindow, logger);
			if (typeof options.app.exit === "function") {
				options.app.exit(0);
				return;
			}
			options.app.quit();
		}, 1_500);
	};
	options.app.on("second-instance", () => {
		if (!mainWindow) {
			return;
		}
		if (mainWindow.isMinimized()) {
			mainWindow.restore();
		}
		mainWindow.show();
		mainWindow.focus();
	});

	await options.app.whenReady();
	logger.info("electron app.whenReady resolved");

	const productPaths = options.productPaths;
	if (productPaths) {
		const validationError = validateProductPaths(productPaths);
		if (validationError) {
			logger.error(`product runtime validation failed: ${validationError.message}`);
			options.onFatalState?.({
				reason: "invalid-runtime",
				error: validationError,
			});
			options.app.quit();
			return;
		}
	}

	let backend: BackendOwner;
	try {
		const backendOptions = buildDefaultBackendOptions(productPaths ?? options.projectRoot);
		const appVersion = resolveAppVersion(options.app);
		backendOptions.environment = {
			...(backendOptions.environment ?? process.env),
			NEO_TTS_APP_VERSION: appVersion,
			NEO_TTS_DISPLAY_VERSION: normalizeDisplayVersion(appVersion),
		};
		backendOptions.onLogLine = (stream, line) => {
			logger.info(`[backend:${stream}] ${line}`);
		};
		logger.info("starting backend process");
		backend = await options.startBackend(backendOptions);
		logger.info(`backend ready origin=${backend.origin}`);
	} catch (error) {
		logger.error(`backend startup failed: ${error instanceof Error ? error.message : String(error)}`);
		options.onFatalState?.({
			reason: "startup-failed",
			error: error instanceof Error ? error : new Error(String(error)),
		});
		options.app.quit();
		return;
	}
	const runtimeInfo = buildElectronRuntimeInfo({
		distributionKind: productPaths?.distributionKind ?? options.distributionKind ?? "installed",
		backendOrigin: backend.origin,
	});
	options.ipcMain.on(APP_GET_RUNTIME_INFO_CHANNEL, (event) => {
		event.returnValue = runtimeInfo;
	});
	options.ipcMain.handle(APP_REQUEST_EXIT_CHANNEL, async () => {
		if (shuttingDown) {
			return;
		}
		shuttingDown = true;
		try {
			await backend.prepareForExit();
		} catch (error) {
			logger.error(
				`backend prepare-exit failed, continuing shutdown: ${
					error instanceof Error ? error.message : String(error)
				}`,
			);
		}
		try {
			await backend.stop();
		} catch (error) {
			logger.error(
				`backend stop failed during shutdown: ${
					error instanceof Error ? error.message : String(error)
				}`,
			);
		}
		requestAppShutdown();
	});
	options.ipcMain.handle(APP_OPEN_EXTERNAL_URL_CHANNEL, async (_event, url) => {
		if (typeof url !== "string" || url.length === 0) {
			return;
		}
		await Promise.resolve(options.openExternalUrl?.(url));
	});
	void backend.exited.then((error) => {
		if (shuttingDown) {
			return;
		}
		shuttingDown = true;
		logger.error(`backend exited unexpectedly: ${error?.message ?? "unknown"}`);
		options.onFatalState?.({
			reason: "backend-exit",
			error,
		});
		requestAppShutdown();
	});

	if (productPaths) {
		try {
			logger.info("clearing renderer cache before loading packaged frontend");
			await Promise.resolve(options.clearRendererCache?.());
		} catch (error) {
			logger.warn(
				`renderer cache clear failed, continuing startup: ${
					error instanceof Error ? error.message : String(error)
				}`,
			);
		}
	}

	mainWindow = options.createMainWindow();
	logger.info("main window created");
	mainWindow.show();
	logger.info("main window shown after backend ready");
	if (productPaths) {
		// 生产模式：后端托管前端静态资源，loadURL 避免 file:// 跨域
		logger.info(`loading renderer via backend origin ${backend.origin}`);
		await Promise.resolve(mainWindow.loadURL(backend.origin));
	} else {
		// 开发模式：从本地 frontend/dist 加载
		logger.info("loading renderer from frontend/dist/index.html");
		await Promise.resolve(mainWindow.loadFile(resolveRendererEntry(options.projectRoot)));
	}
}

export function buildDefaultRunMainOptions(): RunMainOptions {
	const { app, ipcMain, shell, session } = require("electron") as typeof import("electron");
	const { createMainWindow } = require("./window/createMainWindow") as typeof import("./window/createMainWindow");
	const productPaths = buildDefaultProductPaths();
	const runtimeLogPath = path.join(productPaths.logsDir, `electron_${buildLogTimestampSuffix(new Date())}.log`);
	const fallbackLogPath = path.join(os.tmpdir(), "NeoTTS", "electron_bootstrap.log");
	const runtimeLogger = createCompositeRuntimeLogger(
		createFileRuntimeLogger(runtimeLogPath),
		createFileRuntimeLogger(fallbackLogPath),
	);
	runtimeLogger.info("electron runtime logger initialized");
	runtimeLogger.info(`electron log file=${runtimeLogPath}`);
	runtimeLogger.info(`electron fallback log file=${fallbackLogPath}`);
	return {
		app,
		ipcMain,
		projectRoot: path.resolve(__dirname, "..", ".."),
		productPaths,
		startBackend: startBackendProcess,
		createMainWindow,
		clearRendererCache: async () => {
			await session.defaultSession.clearCache();
		},
		openExternalUrl: (url: string) => shell.openExternal(url),
		runtimeLogger,
	};
}

function buildLogTimestampSuffix(now: Date): string {
	const pad = (value: number, size = 2) => String(value).padStart(size, "0");
	return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}_${pad(now.getHours())}-${pad(now.getMinutes())}-${pad(now.getSeconds())}_${pad(now.getMilliseconds(), 3)}`;
}

if (require.main === module) {
	void runMain(buildDefaultRunMainOptions());
}
