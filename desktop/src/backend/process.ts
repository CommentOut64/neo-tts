import { spawn } from "node:child_process";
import path from "node:path";
import process from "node:process";
import { setTimeout as delay } from "node:timers/promises";

export interface BackendOwner {
	origin: string;
	prepareForExit(): Promise<void>;
	stop(): Promise<void>;
	exited: Promise<Error | null>;
}

export interface StartBackendProcessOptions {
	projectRoot: string;
	host?: string;
	port?: number;
	pythonExecutable?: string;
	args?: string[];
	fetchImpl?: typeof fetch;
	healthIntervalMs?: number;
	healthTimeoutMs?: number;
}

const defaultBackendHost = "127.0.0.1";
const defaultBackendPort = 18600;
const defaultHealthIntervalMs = 200;
const defaultHealthTimeoutMs = 15_000;

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

	const child = spawn(pythonExecutable, args, {
		cwd: options.projectRoot,
		stdio: "ignore",
		windowsHide: true,
	});

	const exited = new Promise<Error | null>((resolve) => {
		child.once("error", (error) => {
			resolve(error);
		});
		child.once("exit", (code, signal) => {
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
				return;
			}
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
	projectRoot: string,
): StartBackendProcessOptions {
	return {
		projectRoot,
		host: defaultBackendHost,
		port: defaultBackendPort,
		pythonExecutable: path.join(projectRoot, "runtime", "python", "python.exe"),
		fetchImpl: globalThis.fetch.bind(globalThis),
	};
}
