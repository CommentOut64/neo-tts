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

	const pythonPathEntries = [
		target.resourcesDir,
		target.gptSovitsDir,
		process.env.PYTHONPATH,
	].filter((value): value is string => typeof value === "string" && value.length > 0);
	const runtimePythonDir = path.dirname(target.runtimePython);
	const packagedPathEntries = [runtimePythonDir, process.env.PATH].filter(
		(value): value is string => typeof value === "string" && value.length > 0,
	);
	const cnhubertPath = path.join(target.builtinModelDir, "chinese-hubert-base");
	const bertPath = path.join(target.builtinModelDir, "chinese-roberta-wwm-ext-large");
	const nltkDataPath = path.join(target.resourcesDir, "runtime", "python", "nltk_data");

	return {
		projectRoot: target.runtimeRoot,
		workingDirectory: target.resourcesDir,
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
			...process.env,
			NEO_TTS_DISTRIBUTION_KIND: target.distributionKind,
			NEO_TTS_PROJECT_ROOT: target.runtimeRoot,
			NEO_TTS_RESOURCES_ROOT: target.resourcesDir,
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
			NLTK_DATA: nltkDataPath,
			PATH: packagedPathEntries.join(path.delimiter),
			PYTHONPATH: pythonPathEntries.join(path.delimiter),
		},
		fetchImpl: globalThis.fetch.bind(globalThis),
	};
}
