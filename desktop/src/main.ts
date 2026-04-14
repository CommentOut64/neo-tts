import path from "node:path";
import fs from "node:fs";

import type { BackendOwner, StartBackendProcessOptions } from "./backend/process";
import { buildDefaultBackendOptions, startBackendProcess } from "./backend/process";
import { APP_GET_RUNTIME_INFO_CHANNEL, APP_REQUEST_EXIT_CHANNEL } from "./ipc/channels";
import { buildElectronRuntimeInfo } from "./ipc/runtimeInfo";
import { buildDefaultProductPaths, type DistributionKind, type ProductPaths } from "./runtime/paths";

export interface ElectronAppLike {
	requestSingleInstanceLock(): boolean;
	whenReady(): Promise<void>;
	on(event: string, listener: (...args: unknown[]) => void): void;
	quit(): void;
}

export interface MainWindowLike {
	loadFile(filePath: string): Promise<void> | void;
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
	onFatalState?: (state: FatalState) => void;
}

export function resolveRendererEntry(
	projectRoot: string,
	productPaths?: ProductPaths,
): string {
	if (productPaths) {
		return path.join(productPaths.frontendDir, "index.html");
	}
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
	if (!options.app.requestSingleInstanceLock()) {
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

	const productPaths = options.productPaths;
	if (productPaths) {
		const validationError = validateProductPaths(productPaths);
		if (validationError) {
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
		backend = await options.startBackend(
			buildDefaultBackendOptions(productPaths ?? options.projectRoot),
		);
	} catch (error) {
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
		options.onFatalState?.({
			reason: "backend-exit",
			error,
		});
		options.app.quit();
	});

	mainWindow = options.createMainWindow();
	await Promise.resolve(mainWindow.loadFile(resolveRendererEntry(options.projectRoot, productPaths)));
}

export function buildDefaultRunMainOptions(): RunMainOptions {
	const { app } = require("electron") as typeof import("electron");
	const { ipcMain } = require("electron") as typeof import("electron");
	const { createMainWindow } = require("./window/createMainWindow") as typeof import("./window/createMainWindow");
	return {
		app,
		ipcMain,
		projectRoot: path.resolve(__dirname, "..", ".."),
		productPaths: buildDefaultProductPaths(),
		startBackend: startBackendProcess,
		createMainWindow,
	};
}

if (require.main === module) {
	void runMain(buildDefaultRunMainOptions());
}
