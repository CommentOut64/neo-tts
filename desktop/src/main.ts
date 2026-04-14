import path from "node:path";
import fs from "node:fs";
import os from "node:os";

import type { BackendOwner, StartBackendProcessOptions } from "./backend/process";
import { buildDefaultBackendOptions, startBackendProcess } from "./backend/process";
import { APP_GET_RUNTIME_INFO_CHANNEL, APP_REQUEST_EXIT_CHANNEL } from "./ipc/channels";
import { buildElectronRuntimeInfo } from "./ipc/runtimeInfo";
import { createCompositeRuntimeLogger, createFileRuntimeLogger, createNoopRuntimeLogger, type RuntimeLogger } from "./logging/runtimeLogger";
import { buildDefaultProductPaths, type DistributionKind, type ProductPaths } from "./runtime/paths";

export interface ElectronAppLike {
	requestSingleInstanceLock(): boolean;
	whenReady(): Promise<void>;
	on(event: string, listener: (...args: unknown[]) => void): void;
	quit(): void;
}

export interface MainWindowLike {
	loadFile(filePath: string): Promise<void> | void;
	loadURL(url: string): Promise<void> | void;
	focus(): void;
	isMinimized(): boolean;
	restore(): void;
}

export interface IpcMainLike {
	handle(channel: string, listener: () => Promise<void> | void): void;
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
	runtimeLogger?: RuntimeLogger;
	onFatalState?: (state: FatalState) => void;
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
	options.app.on("second-instance", () => {
		if (!mainWindow) {
			return;
		}
		if (mainWindow.isMinimized()) {
			mainWindow.restore();
		}
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
		await backend.prepareForExit();
		await backend.stop();
		options.app.quit();
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
		options.app.quit();
	});

	mainWindow = options.createMainWindow();
	logger.info("main window created");
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
	const { app } = require("electron") as typeof import("electron");
	const { ipcMain } = require("electron") as typeof import("electron");
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
