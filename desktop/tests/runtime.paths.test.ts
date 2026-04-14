import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { resolveProductPaths } from "../src/runtime/paths";

const tempDirs: string[] = [];

function createTempDir(prefix: string): string {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
	tempDirs.push(dir);
	return dir;
}

describe("product runtime paths", () => {
	afterEach(() => {
		for (const dir of tempDirs.splice(0)) {
			fs.rmSync(dir, { recursive: true, force: true });
		}
	});

	it("uses installed appdata and documents roots when portable flag is absent", () => {
		const workspace = createTempDir("neo-tts-installed-");
		const installRoot = path.join(workspace, "NeoTTS");
		const resourcesRoot = path.join(installRoot, "resources");
		const executablePath = path.join(installRoot, "NeoTTS.exe");

		fs.mkdirSync(resourcesRoot, { recursive: true });

		const paths = resolveProductPaths({
			appName: "NeoTTS",
			executablePath,
			resourcesPath: resourcesRoot,
			localAppDataPath: path.join(workspace, "LocalAppData"),
			documentsPath: path.join(workspace, "Documents"),
		});

		expect(paths.distributionKind).toBe("installed");
		expect(paths.resourcesDir).toBe(path.join(resourcesRoot, "app-runtime"));
		expect(paths.backendDir).toBe(path.join(resourcesRoot, "app-runtime", "backend"));
		expect(paths.gptSovitsDir).toBe(path.join(resourcesRoot, "app-runtime", "GPT_SoVITS"));
		expect(paths.userDataDir).toBe(path.join(workspace, "LocalAppData", "NeoTTS"));
		expect(paths.logsDir).toBe(path.join(workspace, "LocalAppData", "NeoTTS", "logs"));
		expect(paths.exportsDir).toBe(path.join(workspace, "Documents", "NeoTTS", "Exports"));
		expect(paths.runtimePython).toBe(
			path.join(resourcesRoot, "app-runtime", "runtime", "python", "python.exe"),
		);
	});

	it("uses side-by-side data and exports directories when portable flag exists", () => {
		const workspace = createTempDir("neo-tts-portable-");
		const portableRoot = path.join(workspace, "NeoTTS-Portable");
		const resourcesRoot = path.join(portableRoot, "resources");
		const executablePath = path.join(portableRoot, "NeoTTS.exe");

		fs.mkdirSync(resourcesRoot, { recursive: true });
		fs.writeFileSync(path.join(portableRoot, "portable.flag"), "", "utf-8");

		const paths = resolveProductPaths({
			appName: "NeoTTS",
			executablePath,
			resourcesPath: resourcesRoot,
			localAppDataPath: path.join(workspace, "LocalAppData"),
			documentsPath: path.join(workspace, "Documents"),
		});

		expect(paths.distributionKind).toBe("portable");
		expect(paths.resourcesDir).toBe(path.join(resourcesRoot, "app-runtime"));
		expect(paths.backendDir).toBe(path.join(resourcesRoot, "app-runtime", "backend"));
		expect(paths.gptSovitsDir).toBe(path.join(resourcesRoot, "app-runtime", "GPT_SoVITS"));
		expect(paths.userDataDir).toBe(path.join(portableRoot, "data"));
		expect(paths.logsDir).toBe(path.join(portableRoot, "data", "logs"));
		expect(paths.exportsDir).toBe(path.join(portableRoot, "exports"));
		expect(paths.runtimePython).toBe(
			path.join(resourcesRoot, "app-runtime", "runtime", "python", "python.exe"),
		);
	});
});
