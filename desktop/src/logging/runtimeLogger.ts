import fs from "node:fs";
import path from "node:path";

export interface RuntimeLogger {
	info(message: string): void;
	warn(message: string): void;
	error(message: string): void;
}

function formatTimestamp(now: Date): string {
	const pad = (value: number, size = 2) => String(value).padStart(size, "0");
	return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}.${pad(now.getMilliseconds(), 3)}`;
}

function appendLogLine(logFilePath: string, level: "INFO" | "WARN" | "ERROR", message: string): void {
	try {
		fs.mkdirSync(path.dirname(logFilePath), { recursive: true });
		fs.appendFileSync(logFilePath, `${formatTimestamp(new Date())} [${level}] ${message}\n`, "utf-8");
	} catch {
		// 调试日志失败不应阻断主流程。
	}
}

export function createFileRuntimeLogger(logFilePath: string): RuntimeLogger {
	return {
		info(message: string) {
			appendLogLine(logFilePath, "INFO", message);
		},
		warn(message: string) {
			appendLogLine(logFilePath, "WARN", message);
		},
		error(message: string) {
			appendLogLine(logFilePath, "ERROR", message);
		},
	};
}

export function createNoopRuntimeLogger(): RuntimeLogger {
	return {
		info() {},
		warn() {},
		error() {},
	};
}

export function createCompositeRuntimeLogger(...loggers: RuntimeLogger[]): RuntimeLogger {
	return {
		info(message: string) {
			for (const logger of loggers) {
				logger.info(message);
			}
		},
		warn(message: string) {
			for (const logger of loggers) {
				logger.warn(message);
			}
		},
		error(message: string) {
			for (const logger of loggers) {
				logger.error(message);
			}
		},
	};
}
