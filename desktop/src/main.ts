import path from "node:path";
import fs from "node:fs";
import os from "node:os";

import type { BackendOwner, StartBackendProcessOptions } from "./backend/process";
import { buildDefaultBackendOptions, formatBackendMonitorSample, startBackendProcess } from "./backend/process";
import {
	APP_CHECK_UPDATE_CHANNEL,
	APP_GET_RUNTIME_INFO_CHANNEL,
	APP_OPEN_EXTERNAL_URL_CHANNEL,
	APP_REQUEST_EXIT_CHANNEL,
	APP_RESTART_AND_APPLY_UPDATE_CHANNEL,
	APP_START_UPDATE_DOWNLOAD_CHANNEL,
} from "./ipc/channels";
import { buildElectronRuntimeInfo } from "./ipc/runtimeInfo";
import { createCompositeRuntimeLogger, createFileRuntimeLogger, createNoopRuntimeLogger, type RuntimeLogger } from "./logging/runtimeLogger";
import { buildDefaultProductPaths, type DistributionKind, type ProductPaths } from "./runtime/paths";
import {
	connectBootstrapControlFromEnvironment,
	type BootstrapControlClient,
	type ConnectBootstrapControlFromEnvironmentOptions,
} from "./update/bootstrapClient";

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
	handle(channel: string, listener: (...args: unknown[]) => Promise<unknown> | unknown): void;
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
	environment?: NodeJS.ProcessEnv;
	createBootstrapClient?: (
		options: ConnectBootstrapControlFromEnvironmentOptions,
	) => Promise<BootstrapControlClient | null>;
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

type PackagedVoiceConfig = Record<
	string,
	{
		gpt_path?: unknown;
		sovits_path?: unknown;
		ref_audio?: unknown;
	}
>;

function isReadablePath(targetPath: string): boolean {
	try {
		fs.accessSync(targetPath, fs.constants.R_OK);
		return true;
	} catch {
		return false;
	}
}

function resolvePackagedAssetPath(productPaths: ProductPaths, rawPath: string): string {
	const normalized = rawPath.replace(/\\/g, "/");
	if (path.isAbsolute(rawPath)) {
		return rawPath;
	}
	if (normalized === "models" || normalized.startsWith("models/")) {
		return path.join(productPaths.modelsRoot, rawPath);
	}
	if (normalized === "pretrained_models" || normalized.startsWith("pretrained_models/")) {
		return path.join(productPaths.pretrainedModelsRoot, rawPath);
	}
	return path.join(productPaths.appCoreRoot, rawPath);
}

function collectPackagedModelTargets(productPaths: ProductPaths): Array<{ path: string; label: string }> {
	const targets: Array<{ path: string; label: string }> = [
		{
			path: path.join(productPaths.builtinModelDir, "chinese-hubert-base", "config.json"),
			label: "CNHubert config",
		},
		{
			path: path.join(productPaths.builtinModelDir, "chinese-hubert-base", "preprocessor_config.json"),
			label: "CNHubert preprocessor config",
		},
		{
			path: path.join(productPaths.builtinModelDir, "chinese-hubert-base", "pytorch_model.bin"),
			label: "CNHubert weights",
		},
		{
			path: path.join(productPaths.builtinModelDir, "chinese-roberta-wwm-ext-large", "config.json"),
			label: "BERT config",
		},
		{
			path: path.join(productPaths.builtinModelDir, "chinese-roberta-wwm-ext-large", "pytorch_model.bin"),
			label: "BERT weights",
		},
		{
			path: path.join(productPaths.builtinModelDir, "chinese-roberta-wwm-ext-large", "tokenizer.json"),
			label: "BERT tokenizer",
		},
		{
			path: path.join(productPaths.pretrainedModelsDir, "sv", "pretrained_eres2netv2w24s4ep4.ckpt"),
			label: "SV model weights",
		},
		{
			path: path.join(productPaths.pretrainedModelsDir, "fast_langdetect", "lid.176.bin"),
			label: "fast_langdetect model",
		},
	];

	const voicesConfigPath = path.join(productPaths.configDir, "voices.json");
	if (!isReadablePath(voicesConfigPath)) {
		targets.push({ path: voicesConfigPath, label: "builtin voices config" });
		return targets;
	}

	const rawVoices = fs.readFileSync(voicesConfigPath, "utf-8");
	const voices = JSON.parse(rawVoices) as PackagedVoiceConfig;
	for (const [voiceId, voice] of Object.entries(voices)) {
		if (typeof voice.gpt_path === "string") {
			targets.push({
				path: resolvePackagedAssetPath(productPaths, voice.gpt_path),
				label: `voice ${voiceId} GPT weights`,
			});
		}
		if (typeof voice.sovits_path === "string") {
			targets.push({
				path: resolvePackagedAssetPath(productPaths, voice.sovits_path),
				label: `voice ${voiceId} SoVITS weights`,
			});
		}
		if (typeof voice.ref_audio === "string") {
			targets.push({
				path: resolvePackagedAssetPath(productPaths, voice.ref_audio),
				label: `voice ${voiceId} reference audio`,
			});
		}
	}

	return targets;
}

function validateProductPaths(productPaths: ProductPaths): Error | null {
	if (productPaths.resolutionKind === "missing-descriptor") {
		return new Error(
			`Product runtime validation failed: runtime descriptor missing for product root (${productPaths.productRoot})`,
		);
	}

	const requiredTargets: Array<{ path: string; label: string }> = [
		{ path: path.join(productPaths.shellRoot, "NeoTTSApp.exe"), label: "shell executable" },
		{ path: productPaths.runtimePython, label: "bundled python" },
		{ path: productPaths.backendDir, label: "backend dir" },
		{ path: productPaths.frontendDir, label: "frontend dist dir" },
		{ path: path.join(productPaths.frontendDir, "index.html"), label: "frontend index.html" },
		{ path: productPaths.gptSovitsDir, label: "GPT_SoVITS dir" },
		{ path: productPaths.builtinModelDir, label: "builtin model dir" },
		{ path: productPaths.pretrainedModelsDir, label: "pretrained model dir" },
		{ path: productPaths.configDir, label: "config dir" },
	];
	try {
		requiredTargets.push(...collectPackagedModelTargets(productPaths));
	} catch (error) {
		return new Error(
			`Product runtime validation failed: builtin voices config is not readable (${path.join(
				productPaths.configDir,
				"voices.json",
			)}): ${error instanceof Error ? error.message : String(error)}`,
		);
	}
	if (productPaths.distributionKind === "portable") {
		requiredTargets.push({
			path: path.join(productPaths.productRoot, "portable.flag"),
			label: "portable.flag",
		});
	}

	const missing = requiredTargets.filter((target) => !isReadablePath(target.path));
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
	const environment = options.environment ?? process.env;
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

	const createBootstrapClient = options.createBootstrapClient ?? connectBootstrapControlFromEnvironment;
	let bootstrapClient: BootstrapControlClient | null = null;
	try {
		bootstrapClient = await createBootstrapClient({
			env: environment,
			fetchImpl: globalThis.fetch.bind(globalThis),
		});
		if (bootstrapClient) {
			logger.info(
				`bootstrap control connected origin=${bootstrapClient.origin} apiVersion=${bootstrapClient.apiVersion} bootstrapVersion=${bootstrapClient.bootstrapVersion} sessionId=${bootstrapClient.sessionId}`,
			);
		}
	} catch (error) {
		logger.warn(
			`bootstrap control negotiation failed, update features disabled: ${
				error instanceof Error ? error.message : String(error)
			}`,
		);
	}

	const productPaths = options.productPaths;
	if (productPaths) {
		const validationError = validateProductPaths(productPaths);
		if (validationError) {
			logger.error(`product runtime validation failed: ${validationError.message}`);
			await reportBootstrapSessionFailed(bootstrapClient, logger, "invalid-runtime", validationError);
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
		backendOptions.onMonitorSample = (sample) => {
			logger.info(`[backend:monitor] ${formatBackendMonitorSample(sample)}`);
		};
		logger.info("starting backend process");
		backend = await options.startBackend(backendOptions);
		logger.info(`backend ready origin=${backend.origin}`);
	} catch (error) {
		logger.error(`backend startup failed: ${error instanceof Error ? error.message : String(error)}`);
		await reportBootstrapSessionFailed(
			bootstrapClient,
			logger,
			"startup-failed",
			error instanceof Error ? error : new Error(String(error)),
		);
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
	options.ipcMain.handle(APP_CHECK_UPDATE_CHANNEL, async (_event, request) => {
		return await requireBootstrapControlClient(bootstrapClient).checkForUpdate(
			(request ?? { channel: "stable", automatic: false }) as Parameters<
				BootstrapControlClient["checkForUpdate"]
			>[0],
		);
	});
	options.ipcMain.handle(APP_START_UPDATE_DOWNLOAD_CHANNEL, async (_event, request) => {
		return await requireBootstrapControlClient(bootstrapClient).downloadUpdate(
			(request ?? {}) as Parameters<BootstrapControlClient["downloadUpdate"]>[0],
		);
	});
	options.ipcMain.handle(APP_RESTART_AND_APPLY_UPDATE_CHANNEL, async (_event, request) => {
		const client = requireBootstrapControlClient(bootstrapClient);
		const response = await client.restartAndApplyUpdate(
			(request ?? {}) as Parameters<BootstrapControlClient["restartAndApplyUpdate"]>[0],
		);
		await reportBootstrapSessionRestartForUpdate(client, logger);
		if (!shuttingDown) {
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
		}
		return response;
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
		void reportBootstrapSessionFailed(bootstrapClient, logger, "backend-exit", error);
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
	await reportBootstrapSessionReady(bootstrapClient, logger);
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

function requireBootstrapControlClient(
	client: BootstrapControlClient | null,
): BootstrapControlClient {
	if (client !== null) {
		return client;
	}
	throw new Error("bootstrap control client is unavailable");
}

async function reportBootstrapSessionReady(
	client: BootstrapControlClient | null,
	logger: RuntimeLogger,
): Promise<void> {
	if (!client) {
		return;
	}
	try {
		await client.reportSessionReady({
			sessionId: client.sessionId,
		});
	} catch (error) {
		logger.warn(
			`failed to report bootstrap session-ready: ${
				error instanceof Error ? error.message : String(error)
			}`,
		);
	}
}

async function reportBootstrapSessionRestartForUpdate(
	client: BootstrapControlClient | null,
	logger: RuntimeLogger,
): Promise<void> {
	if (!client) {
		return;
	}
	try {
		await client.reportRestartForUpdate({
			sessionId: client.sessionId,
		});
	} catch (error) {
		logger.warn(
			`failed to report bootstrap restart-for-update: ${
				error instanceof Error ? error.message : String(error)
			}`,
		);
	}
}

async function reportBootstrapSessionFailed(
	client: BootstrapControlClient | null,
	logger: RuntimeLogger,
	code: FatalState["reason"],
	error: Error | null,
): Promise<void> {
	if (!client) {
		return;
	}
	try {
		await client.reportSessionFailed({
			sessionId: client.sessionId,
			code,
			message: error?.message ?? code,
		});
	} catch (reportError) {
		logger.warn(
			`failed to report bootstrap session failure: ${
				reportError instanceof Error ? reportError.message : String(reportError)
			}`,
		);
	}
}
