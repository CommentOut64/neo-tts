import path from "node:path";

import type { BackendOwner, StartBackendProcessOptions } from "./backend/process";
import { buildDefaultBackendOptions, startBackendProcess } from "./backend/process";
import { APP_REQUEST_EXIT_CHANNEL } from "./ipc/channels";

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
}

export interface FatalState {
	reason: "backend-exit";
	error: Error | null;
}

export interface RunMainOptions {
	app: ElectronAppLike;
	ipcMain: IpcMainLike;
	projectRoot: string;
	startBackend: (options: StartBackendProcessOptions) => Promise<BackendOwner>;
	createMainWindow: () => MainWindowLike;
	onFatalState?: (state: FatalState) => void;
}

export function resolveRendererEntry(projectRoot: string): string {
	return path.join(projectRoot, "frontend", "dist", "index.html");
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

	const backend = await options.startBackend(
		buildDefaultBackendOptions(options.projectRoot),
	);
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
	await Promise.resolve(mainWindow.loadFile(resolveRendererEntry(options.projectRoot)));
}

export function buildDefaultRunMainOptions(): RunMainOptions {
	const { app } = require("electron") as typeof import("electron");
	const { ipcMain } = require("electron") as typeof import("electron");
	const { createMainWindow } = require("./window/createMainWindow") as typeof import("./window/createMainWindow");
	return {
		app,
		ipcMain,
		projectRoot: path.resolve(__dirname, "..", ".."),
		startBackend: startBackendProcess,
		createMainWindow,
	};
}

if (require.main === module) {
	void runMain(buildDefaultRunMainOptions());
}
