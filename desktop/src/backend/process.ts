import { execSync, spawn } from "node:child_process";
import path from "node:path";
import process from "node:process";
import { setTimeout as delay } from "node:timers/promises";

import type { ProductPaths } from "../runtime/paths";

export interface BackendOwner {
	origin: string;
	prepareForExit(): Promise<void>;
	stop(): Promise<void>;
	exited: Promise<Error | null>;
}

export interface BackendProcessMonitorSample {
	pid: number;
	cpuSeconds: number | null;
	workingSetMb: number | null;
	threadCount: number | null;
	gpuMemoryMb: number | null;
	sampledAt: string;
	error?: string;
}

export interface StartBackendProcessOptions {
	projectRoot: string;
	workingDirectory?: string;
	host?: string;
	port?: number;
	pythonExecutable?: string;
	args?: string[];
	environment?: NodeJS.ProcessEnv;
	fetchImpl?: typeof fetch;
	healthIntervalMs?: number;
	healthTimeoutMs?: number;
	onLogLine?: (stream: "stdout" | "stderr", line: string) => void;
	onMonitorSample?: (sample: BackendProcessMonitorSample) => void;
	monitorIntervalMs?: number;
	sampleProcessMonitor?: (pid: number) => BackendProcessMonitorSample | null;
}

const defaultBackendHost = "127.0.0.1";
const defaultBackendPort = 18600;
const defaultHealthIntervalMs = 200;
const defaultHealthTimeoutMs = 30_000;
const defaultMonitorIntervalMs = 5_000;
// 产品态允许稍长冷启动窗口，但保持在 40s 以内，避免无反馈等待过久。
const packagedHealthTimeoutMs = 40_000;
const netstatProbeTimeoutMs = 5_000;
const monitorProbeTimeoutMs = 5_000;
const packagedBackendPassthroughEnvKeys = [
	"NEO_TTS_OWNER_CONTROL_ORIGIN",
	"NEO_TTS_OWNER_CONTROL_TOKEN",
	"NEO_TTS_OWNER_SESSION_ID",
	"NEO_TTS_BOOTSTRAP_CONTROL_ORIGIN",
	"NEO_TTS_BOOTSTRAP_API_VERSION",
] as const;
const packagedBackendControlEnvKeys = [
	"NEO_TTS_STDIN_WATCHDOG_ENABLED",
	"GPT_SOVITS_PRELOAD_ON_START",
	"GPT_SOVITS_PRELOAD_VOICES",
	"GPT_SOVITS_GPU_OFFLOAD_ENABLED",
	"GPT_SOVITS_GPU_MIN_FREE_MB",
	"GPT_SOVITS_GPU_RESERVE_MB_FOR_LOAD",
	"GPT_SOVITS_EDIT_SESSION_STAGING_TTL_SECONDS",
	"GPT_SOVITS_PREPEND_COMMA_TO_SHORT_ENGLISH",
] as const;
const packagedBackendSystemEnvKeys = [
	"SystemRoot",
	"WINDIR",
	"TEMP",
	"TMP",
	"COMSPEC",
	"PATHEXT",
	"NUMBER_OF_PROCESSORS",
	"PROCESSOR_ARCHITECTURE",
] as const;

function readPortNetstatOutput(port: number): string {
	const command = `netstat -ano -p TCP | findstr /R /C:":${String(port)} "`;
	try {
		return execSync(command, {
			encoding: "utf-8",
			timeout: netstatProbeTimeoutMs,
			windowsHide: true,
		});
	} catch (error) {
		// findstr 未匹配时也会走异常，按“无占用”处理。
		if (typeof error === "object" && error !== null && "stdout" in error) {
			const stdout = Reflect.get(error, "stdout");
			if (typeof stdout === "string") {
				return stdout;
			}
		}
		return "";
	}
}

export function parsePortOccupierPids(
	netstatOutput: string,
	port: number,
	options?: { selfPid?: number },
): number[] {
	const pidSet = new Set<number>();
	const selfPid = options?.selfPid ?? process.pid;
	const portSuffix = `:${String(port)}`;
	for (const line of netstatOutput.split(/\r?\n/)) {
		const trimmed = line.trim();
		if (trimmed.length === 0) {
			continue;
		}
		const parts = trimmed.split(/\s+/);
		if (parts.length < 4) {
			continue;
		}
		const localAddress = parts[1]?.toLowerCase() ?? "";
		if (!localAddress.endsWith(portSuffix)) {
			continue;
		}
		const pid = Number(parts[parts.length - 1]);
		if (Number.isFinite(pid) && pid > 0 && pid !== selfPid) {
			pidSet.add(pid);
		}
	}
	return [...pidSet].sort((left, right) => left - right);
}

export function parseNvidiaSmiComputeAppsMemoryMiB(csvOutput: string, pid: number): number | null {
	let total = 0;
	let matched = false;
	for (const line of csvOutput.split(/\r?\n/)) {
		const trimmed = line.trim();
		if (trimmed.length === 0) {
			continue;
		}
		const parts = trimmed.split(",");
		if (parts.length < 2) {
			continue;
		}
		const rowPid = Number(parts[0]?.trim());
		const usedMemoryMiB = Number(parts[1]?.trim());
		if (!Number.isFinite(rowPid) || !Number.isFinite(usedMemoryMiB) || rowPid !== pid) {
			continue;
		}
		matched = true;
		total += usedMemoryMiB;
	}
	return matched ? total : null;
}

interface WindowsBackendProcessSnapshot {
	cpuSeconds: number | null;
	workingSetMb: number | null;
	threadCount: number | null;
}

function parseWindowsProcessSnapshot(jsonText: string): WindowsBackendProcessSnapshot {
	const parsed = JSON.parse(jsonText) as {
		CPU?: number;
		WorkingSet64?: number;
		ThreadCount?: number;
	};
	return {
		cpuSeconds: typeof parsed.CPU === "number" ? parsed.CPU : null,
		workingSetMb: typeof parsed.WorkingSet64 === "number" ? parsed.WorkingSet64 / (1024 * 1024) : null,
		threadCount: typeof parsed.ThreadCount === "number" ? parsed.ThreadCount : null,
	};
}

interface WindowsBackendProcessMonitorDependencies {
	now?: () => Date;
	runCommand(command: string): string;
}

function defaultMonitorCommandRunner(command: string): string {
	return execSync(command, {
		encoding: "utf-8",
		timeout: monitorProbeTimeoutMs,
		windowsHide: true,
	});
}

export function sampleWindowsBackendProcess(
	pid: number,
	dependencies?: WindowsBackendProcessMonitorDependencies,
): BackendProcessMonitorSample {
	const runCommand = dependencies?.runCommand ?? defaultMonitorCommandRunner;
	const now = dependencies?.now ?? (() => new Date());
	try {
		const processJson = runCommand(
			`powershell -NoProfile -Command "Get-Process -Id ${String(pid)} | Select-Object Id,CPU,WorkingSet64,@{Name='ThreadCount';Expression={$_.Threads.Count}} | ConvertTo-Json -Compress"`,
		);
		const processSnapshot = parseWindowsProcessSnapshot(processJson);
		let gpuMemoryMb: number | null = null;
		try {
			const gpuCsv = runCommand(
				"nvidia-smi --query-compute-apps=pid,used_gpu_memory --format=csv,noheader,nounits",
			);
			gpuMemoryMb = parseNvidiaSmiComputeAppsMemoryMiB(gpuCsv, pid);
		} catch {
			gpuMemoryMb = null;
		}
		return {
			pid,
			cpuSeconds: processSnapshot.cpuSeconds,
			workingSetMb: processSnapshot.workingSetMb,
			threadCount: processSnapshot.threadCount,
			gpuMemoryMb,
			sampledAt: now().toISOString(),
		};
	} catch (error) {
		return {
			pid,
			cpuSeconds: null,
			workingSetMb: null,
			threadCount: null,
			gpuMemoryMb: null,
			sampledAt: now().toISOString(),
			error: error instanceof Error ? error.message : String(error),
		};
	}
}

export function formatBackendMonitorSample(sample: BackendProcessMonitorSample): string {
	const parts = [
		`pid=${String(sample.pid)}`,
		`rss_mb=${sample.workingSetMb === null ? "na" : sample.workingSetMb.toFixed(1)}`,
		`cpu_s=${sample.cpuSeconds === null ? "na" : sample.cpuSeconds.toFixed(1)}`,
		`threads=${sample.threadCount === null ? "na" : String(sample.threadCount)}`,
		`gpu_mb=${sample.gpuMemoryMb === null ? "na" : String(sample.gpuMemoryMb)}`,
		`sampled_at=${sample.sampledAt}`,
	];
	if (typeof sample.error === "string" && sample.error.length > 0) {
		parts.push(`error=${sample.error}`);
	}
	return parts.join(" ");
}

/**
 * 清理占用目标端口的残留进程（Windows 安全网）。
 *
 * 当上一次 Electron 被强杀而 Python 后端存活时，端口仍被占用。
 * 本函数在启动新后端之前尝试检测并强制终止占用进程。
 * 清理失败不阻塞启动，让后续 health check 自然超时报错。
 */
function ensurePortAvailable(port: number): void {
	if (process.platform !== "win32") {
		return;
	}
	const occupantPids = parsePortOccupierPids(readPortNetstatOutput(port), port);
	if (occupantPids.length === 0) {
		return;
	}

	for (const pid of occupantPids) {
		try {
			execSync(`taskkill /PID ${String(pid)} /F`, {
				encoding: "utf-8",
				timeout: netstatProbeTimeoutMs,
				windowsHide: true,
			});
		} catch {
			// 权限不足或进程已退出，不阻塞，后续统一二次校验。
		}
	}

	const remainingPids = parsePortOccupierPids(readPortNetstatOutput(port), port);
	if (remainingPids.length > 0) {
		throw new Error(
			`backend port ${String(port)} is still occupied by PID(s): ${remainingPids.join(", ")}`,
		);
	}
}

export async function startBackendProcess(
	options: StartBackendProcessOptions,
): Promise<BackendOwner> {
	const host = options.host ?? defaultBackendHost;
	const port = options.port ?? defaultBackendPort;
	const origin = `http://${host}:${port}`;
	const fetchImpl = options.fetchImpl ?? fetch;

	const pythonExecutable =
		options.pythonExecutable ??
		path.join(options.projectRoot, "runtime", "python", "python.exe");
	const args = options.args ?? [
		"-m",
		"backend.app.cli",
		"--host",
		host,
		"--port",
		String(port),
	];

	ensurePortAvailable(port);

	const enableRealtimeLog = typeof options.onLogLine === "function";
	const child = spawn(pythonExecutable, args, {
		cwd: options.workingDirectory ?? options.projectRoot,
		env: options.environment,
		// stdin pipe 作为生命线：父进程退出/被杀时管道断开，
		// Python 侧 stdin 看门狗检测到 EOF 后自动退出，防止孤儿进程。
		stdio: enableRealtimeLog ? ["pipe", "pipe", "pipe"] : ["pipe", "ignore", "ignore"],
		windowsHide: true,
	});
	if (enableRealtimeLog) {
		bindRealtimeProcessLog(child.stdout, "stdout", options.onLogLine);
		bindRealtimeProcessLog(child.stderr, "stderr", options.onLogLine);
	}
	const sampleProcessMonitor =
		options.sampleProcessMonitor ??
		((pid: number) => (process.platform === "win32" ? sampleWindowsBackendProcess(pid) : null));
	const monitorTimer =
		typeof options.onMonitorSample === "function" && typeof child.pid === "number"
			? globalThis.setInterval(() => {
					if (child.exitCode !== null || child.killed) {
						return;
					}
					try {
						const sample = sampleProcessMonitor(child.pid!);
						if (sample) {
							options.onMonitorSample?.(sample);
						}
					} catch (error) {
						options.onMonitorSample?.({
							pid: child.pid!,
							cpuSeconds: null,
							workingSetMb: null,
							threadCount: null,
							gpuMemoryMb: null,
							sampledAt: new Date().toISOString(),
							error: error instanceof Error ? error.message : String(error),
						});
					}
				}, options.monitorIntervalMs ?? defaultMonitorIntervalMs)
			: null;

	const exited = new Promise<Error | null>((resolve) => {
		child.once("error", (error) => {
			if (monitorTimer !== null) {
				globalThis.clearInterval(monitorTimer);
			}
			resolve(error);
		});
		child.once("exit", (code, signal) => {
			if (monitorTimer !== null) {
				globalThis.clearInterval(monitorTimer);
			}
			if (code === 0 || signal === "SIGTERM") {
				resolve(null);
				return;
			}
			resolve(
				new Error(
					`backend exited unexpectedly code=${String(code)} signal=${String(signal)}`,
				),
			);
		});
	});

	try {
		await waitForHealthy({
			origin,
			fetchImpl,
			intervalMs: options.healthIntervalMs ?? defaultHealthIntervalMs,
			timeoutMs: options.healthTimeoutMs ?? defaultHealthTimeoutMs,
		});
	} catch (error) {
		child.kill();
		throw error;
	}

	return {
		origin,
		async prepareForExit() {
			const response = await fetchImpl(`${origin}/v1/system/prepare-exit`, {
				method: "POST",
			});
			if (!response.ok) {
				throw new Error(`backend prepare-exit returned ${response.status}`);
			}
		},
		async stop() {
			if (child.exitCode !== null || child.killed) {
				if (monitorTimer !== null) {
					globalThis.clearInterval(monitorTimer);
				}
				return;
			}
			child.stdin?.end();
			child.kill();
			await Promise.race([
				exited,
				delay(2_000).then(() => {
					if (child.exitCode === null && !child.killed) {
						child.kill("SIGKILL");
					}
				}),
			]);
		},
		exited,
	};
}

function bindRealtimeProcessLog(
	stream: NodeJS.ReadableStream | null,
	streamName: "stdout" | "stderr",
	onLogLine?: (stream: "stdout" | "stderr", line: string) => void,
): void {
	if (!stream || typeof onLogLine !== "function") {
		return;
	}
	let buffer = "";
	stream.setEncoding("utf8");
	stream.on("data", (chunk: string) => {
		buffer += chunk;
		const lines = buffer.split(/\r?\n/);
		buffer = lines.pop() ?? "";
		for (const line of lines) {
			const trimmed = line.trim();
			if (trimmed.length > 0) {
				onLogLine(streamName, trimmed);
			}
		}
	});
	stream.on("end", () => {
		const trimmed = buffer.trim();
		if (trimmed.length > 0) {
			onLogLine(streamName, trimmed);
		}
	});
}

interface WaitForHealthyOptions {
	origin: string;
	fetchImpl: typeof fetch;
	intervalMs: number;
	timeoutMs: number;
}

async function waitForHealthy(options: WaitForHealthyOptions): Promise<void> {
	const deadline = Date.now() + options.timeoutMs;
	let lastError: unknown = null;

	while (Date.now() < deadline) {
		try {
			const response = await options.fetchImpl(`${options.origin}/health`);
			if (response.ok) {
				return;
			}
			lastError = new Error(`backend health returned ${response.status}`);
		} catch (error) {
			lastError = error;
		}
		await delay(options.intervalMs);
	}

	if (lastError instanceof Error) {
		throw lastError;
	}
	throw new Error("backend health check timed out");
}

export function buildDefaultBackendOptions(
	target: string | ProductPaths,
): StartBackendProcessOptions {
	if (typeof target === "string") {
		return {
			projectRoot: target,
			host: defaultBackendHost,
			port: defaultBackendPort,
			healthTimeoutMs: defaultHealthTimeoutMs,
			pythonExecutable: path.join(target, "runtime", "python", "python.exe"),
			args: [
				"-m",
				"backend.app.cli",
				"--host",
				defaultBackendHost,
				"--port",
				String(defaultBackendPort),
			],
			fetchImpl: globalThis.fetch.bind(globalThis),
		};
	}

	const productRoot = target.productRoot ?? target.bootstrapRoot ?? target.runtimeRoot;
	const appCoreRoot = target.appCoreRoot ?? target.resourcesDir;
	const runtimeLayerRoot = target.runtimeRoot;
	const supportAssetsRoot = target.supportAssetsRoot ?? target.resourcesDir;
	const pythonPathEntries = [appCoreRoot, target.gptSovitsDir];
	const runtimePythonDir = path.dirname(target.runtimePython);
	const packagedPathEntries = buildPackagedBackendPathEntries(runtimePythonDir);
	const cnhubertPath = path.join(target.builtinModelDir, "chinese-hubert-base");
	const bertPath = path.join(target.builtinModelDir, "chinese-roberta-wwm-ext-large");
	const svModelPath = path.join(target.pretrainedModelsDir, "sv", "pretrained_eres2netv2w24s4ep4.ckpt");
	const nltkDataPath = path.join(runtimePythonDir, "nltk_data");

	return {
		projectRoot: productRoot,
		workingDirectory: appCoreRoot,
		host: defaultBackendHost,
		port: defaultBackendPort,
		healthTimeoutMs: packagedHealthTimeoutMs,
		pythonExecutable: target.runtimePython,
		args: [
			"-m",
			"backend.app.cli",
			"--host",
			defaultBackendHost,
			"--port",
			String(defaultBackendPort),
		],
		environment: {
			...pickProcessEnvironment(packagedBackendSystemEnvKeys),
			...pickProcessEnvironment(packagedBackendPassthroughEnvKeys),
			...pickProcessEnvironment(packagedBackendControlEnvKeys),
			NEO_TTS_DISTRIBUTION_KIND: target.distributionKind,
			NEO_TTS_PROJECT_ROOT: productRoot,
			NEO_TTS_RUNTIME_DESCRIPTOR: target.runtimeDescriptorPath ?? "",
			NEO_TTS_APP_CORE_ROOT: appCoreRoot,
			NEO_TTS_RUNTIME_ROOT: runtimeLayerRoot,
			NEO_TTS_MODELS_ROOT: supportAssetsRoot,
			NEO_TTS_PRETRAINED_MODELS_ROOT: supportAssetsRoot,
			NEO_TTS_RESOURCES_ROOT: appCoreRoot,
			NEO_TTS_GPT_SOVITS_ROOT: target.gptSovitsDir,
			NEO_TTS_USER_DATA_ROOT: target.userDataDir,
			NEO_TTS_EXPORTS_ROOT: target.exportsDir,
			NEO_TTS_LOGS_ROOT: target.logsDir,
			CNHUBERT_PATH: cnhubertPath,
			GPT_SOVITS_CNHUBERT_PATH: cnhubertPath,
			cnhubert_base_path: cnhubertPath,
			BERT_PATH: bertPath,
			GPT_SOVITS_BERT_PATH: bertPath,
			bert_path: bertPath,
			SV_MODEL_PATH: svModelPath,
			NLTK_DATA: nltkDataPath,
			PATH: packagedPathEntries.join(path.delimiter),
			PYTHONNOUSERSITE: "1",
			PYTHONPATH: pythonPathEntries.join(path.delimiter),
		},
		fetchImpl: globalThis.fetch.bind(globalThis),
	};
}

function buildPackagedBackendPathEntries(runtimePythonDir: string): string[] {
	const windowsRoot = readProcessEnvironment("SystemRoot") ?? readProcessEnvironment("WINDIR");
	return uniqueNonEmptyStrings([
		runtimePythonDir,
		windowsRoot ? path.join(windowsRoot, "System32") : undefined,
		windowsRoot,
		windowsRoot ? path.join(windowsRoot, "System32", "WindowsPowerShell", "v1.0") : undefined,
	]);
}

function pickProcessEnvironment(keys: readonly string[]): NodeJS.ProcessEnv {
	const environment: NodeJS.ProcessEnv = {};
	for (const key of keys) {
		const value = readProcessEnvironment(key);
		if (typeof value === "string" && value.length > 0) {
			environment[key] = value;
		}
	}
	return environment;
}

function readProcessEnvironment(name: string): string | undefined {
	if (typeof process.env[name] === "string") {
		return process.env[name];
	}
	const normalizedName = name.toLowerCase();
	const matchingKey = Object.keys(process.env).find(
		(key) => key.toLowerCase() === normalizedName,
	);
	return matchingKey ? process.env[matchingKey] : undefined;
}

function uniqueNonEmptyStrings(values: Array<string | undefined>): string[] {
	const seen = new Set<string>();
	const result: string[] = [];
	for (const value of values) {
		if (typeof value !== "string" || value.length === 0 || seen.has(value)) {
			continue;
		}
		seen.add(value);
		result.push(value);
	}
	return result;
}
