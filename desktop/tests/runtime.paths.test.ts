import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { resolveProductPaths, type ProductPaths } from "../src/runtime/paths";

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

	it("falls back to legacy installed layout in development mode when descriptor is absent", () => {
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
			mode: "development",
		});

		expect(paths.resolutionKind).toBe("development-fallback");
		expect(paths.distributionKind).toBe("installed");
		expect(paths.bootstrapRoot).toBe(installRoot);
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

	it("falls back to legacy portable layout in development mode when descriptor is absent", () => {
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
			mode: "development",
		});

		expect(paths.resolutionKind).toBe("development-fallback");
		expect(paths.distributionKind).toBe("portable");
		expect(paths.bootstrapRoot).toBe(portableRoot);
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

	it("resolves installed layered roots from bootstrap state/current.json in product mode", () => {
		const workspace = createTempDir("neo-tts-layered-installed-");
		const installRoot = path.join(workspace, "NeoTTS");
		const executablePath = path.join(installRoot, "NeoTTS.exe");
		const descriptorPath = path.join(installRoot, "state", "current.json");
		fs.mkdirSync(path.dirname(descriptorPath), { recursive: true });
		fs.writeFileSync(
			descriptorPath,
			JSON.stringify(
				{
					schemaVersion: 1,
					distributionKind: "installed",
					channel: "stable",
					releaseId: "v0.0.1",
					packages: {
						bootstrap: { version: "1.1.0", root: path.join(installRoot, "packages", "bootstrap", "1.1.0") },
						"update-agent": { version: "1.1.0", root: path.join(installRoot, "packages", "update-agent", "1.1.0") },
						shell: { version: "v0.0.1", root: path.join(installRoot, "packages", "shell", "v0.0.1") },
						"app-core": { version: "v0.0.1", root: path.join(installRoot, "packages", "app-core", "v0.0.1") },
						runtime: { version: "py311-cu124-v1", root: path.join(installRoot, "packages", "runtime", "py311-cu124-v1") },
						models: { version: "builtin-v1", root: path.join(installRoot, "packages", "models", "builtin-v1") },
						"pretrained-models": { version: "support-v1", root: path.join(installRoot, "packages", "pretrained-models", "support-v1") },
					},
					paths: {
						userDataRoot: path.join(workspace, "LocalAppData", "NeoTTS"),
						exportsRoot: path.join(workspace, "Documents", "NeoTTS", "Exports"),
					},
				},
				null,
				2,
			),
			"utf-8",
		);

		const paths = resolveProductPaths({
			appName: "NeoTTS",
			executablePath,
			resourcesPath: path.join(installRoot, "resources"),
			localAppDataPath: path.join(workspace, "LocalAppData"),
			documentsPath: path.join(workspace, "Documents"),
		});

		expect(paths.resolutionKind).toBe("descriptor");
		expect(paths.runtimeDescriptorPath).toBe(descriptorPath);
		expect((paths as ProductPaths & { productRoot?: string }).productRoot).toBe(installRoot);
		expect(paths.bootstrapRoot).toBe(path.join(installRoot, "packages", "bootstrap", "1.1.0"));
		expect(paths.shellRoot).toBe(path.join(installRoot, "packages", "shell", "v0.0.1"));
		expect(paths.appCoreRoot).toBe(path.join(installRoot, "packages", "app-core", "v0.0.1"));
		expect(paths.runtimeRoot).toBe(path.join(installRoot, "packages", "runtime", "py311-cu124-v1"));
		expect(paths.modelsRoot).toBe(path.join(installRoot, "packages", "models", "builtin-v1"));
		expect(paths.pretrainedModelsRoot).toBe(path.join(installRoot, "packages", "pretrained-models", "support-v1"));
		expect(paths.backendDir).toBe(path.join(paths.appCoreRoot, "backend"));
		expect(paths.runtimePython).toBe(path.join(paths.runtimeRoot, "runtime", "python", "python.exe"));
		expect(paths.builtinModelDir).toBe(path.join(paths.modelsRoot, "models", "builtin"));
		expect(paths.pretrainedModelsDir).toBe(path.join(paths.pretrainedModelsRoot, "pretrained_models"));
	});

	it("resolves portable layered roots from NEO_TTS_RUNTIME_DESCRIPTOR when provided", () => {
		const workspace = createTempDir("neo-tts-layered-portable-");
		const portableRoot = path.join(workspace, "NeoTTS-Portable");
		const executablePath = path.join(portableRoot, "NeoTTS.exe");
		const descriptorPath = path.join(portableRoot, "state", "current.json");
		fs.mkdirSync(portableRoot, { recursive: true });
		fs.mkdirSync(path.dirname(descriptorPath), { recursive: true });
		fs.writeFileSync(path.join(portableRoot, "portable.flag"), "", "utf-8");
		fs.writeFileSync(
			descriptorPath,
			JSON.stringify(
				{
					schemaVersion: 1,
					distributionKind: "portable",
					channel: "stable",
					releaseId: "v0.0.1",
					packages: {
						bootstrap: { version: "1.1.0", root: path.join(portableRoot, "packages", "bootstrap", "1.1.0") },
						"update-agent": { version: "1.1.0", root: path.join(portableRoot, "packages", "update-agent", "1.1.0") },
						shell: { version: "v0.0.1", root: path.join(portableRoot, "packages", "shell", "v0.0.1") },
						"app-core": { version: "v0.0.1", root: path.join(portableRoot, "packages", "app-core", "v0.0.1") },
						runtime: { version: "py311-cu124-v1", root: path.join(portableRoot, "packages", "runtime", "py311-cu124-v1") },
						models: { version: "builtin-v1", root: path.join(portableRoot, "packages", "models", "builtin-v1") },
						"pretrained-models": { version: "support-v1", root: path.join(portableRoot, "packages", "pretrained-models", "support-v1") },
					},
					paths: {
						userDataRoot: path.join(portableRoot, "data"),
						exportsRoot: path.join(portableRoot, "exports"),
					},
				},
				null,
				2,
			),
			"utf-8",
		);

		const paths = resolveProductPaths({
			appName: "NeoTTS",
			executablePath,
			resourcesPath: path.join(portableRoot, "resources"),
			localAppDataPath: path.join(workspace, "LocalAppData"),
			documentsPath: path.join(workspace, "Documents"),
			env: {
				NEO_TTS_RUNTIME_DESCRIPTOR: descriptorPath,
			},
		});

		expect(paths.resolutionKind).toBe("descriptor");
		expect(paths.runtimeDescriptorPath).toBe(descriptorPath);
		expect(paths.distributionKind).toBe("portable");
		expect((paths as ProductPaths & { productRoot?: string }).productRoot).toBe(portableRoot);
		expect(paths.userDataDir).toBe(path.join(portableRoot, "data"));
		expect(paths.exportsDir).toBe(path.join(portableRoot, "exports"));
		expect(paths.shellRoot).toBe(path.join(portableRoot, "packages", "shell", "v0.0.1"));
		expect(paths.frontendDir).toBe(path.join(paths.appCoreRoot, "frontend-dist"));
	});

	it("resolves portable layered roots from version-only descriptor entries after moving the portable root", () => {
		const workspace = createTempDir("neo-tts-layered-portable-relocated-");
		const portableRoot = path.join(workspace, "MovedPortable", "NeoTTS");
		const executablePath = path.join(portableRoot, "NeoTTS.exe");
		const descriptorPath = path.join(portableRoot, "state", "current.json");
		fs.mkdirSync(portableRoot, { recursive: true });
		fs.mkdirSync(path.dirname(descriptorPath), { recursive: true });
		fs.writeFileSync(path.join(portableRoot, "portable.flag"), "", "utf-8");
		fs.writeFileSync(
			descriptorPath,
			JSON.stringify(
				{
					schemaVersion: 1,
					distributionKind: "portable",
					channel: "stable",
					releaseId: "v0.0.1",
					packages: {
						bootstrap: { version: "1.1.0" },
						"update-agent": { version: "1.1.0" },
						shell: { version: "v0.0.1" },
						"app-core": { version: "v0.0.1" },
						runtime: { version: "py311-cu124-v1" },
						models: { version: "builtin-v1" },
						"pretrained-models": { version: "support-v1" },
					},
					paths: {
						userDataRoot: "./data",
						exportsRoot: "./exports",
					},
				},
				null,
				2,
			),
			"utf-8",
		);

		const paths = resolveProductPaths({
			appName: "NeoTTS",
			executablePath,
			resourcesPath: path.join(portableRoot, "resources"),
			localAppDataPath: path.join(workspace, "LocalAppData"),
			documentsPath: path.join(workspace, "Documents"),
			env: {
				NEO_TTS_RUNTIME_DESCRIPTOR: descriptorPath,
			},
		});

		expect(paths.resolutionKind).toBe("descriptor");
		expect(paths.distributionKind).toBe("portable");
		expect(paths.bootstrapRoot).toBe(path.join(portableRoot, "packages", "bootstrap", "1.1.0"));
		expect(paths.updateAgentRoot).toBe(path.join(portableRoot, "packages", "update-agent", "1.1.0"));
		expect(paths.shellRoot).toBe(path.join(portableRoot, "packages", "shell", "v0.0.1"));
		expect(paths.appCoreRoot).toBe(path.join(portableRoot, "packages", "app-core", "v0.0.1"));
		expect(paths.runtimeRoot).toBe(path.join(portableRoot, "packages", "runtime", "py311-cu124-v1"));
		expect(paths.modelsRoot).toBe(path.join(portableRoot, "packages", "models", "builtin-v1"));
		expect(paths.pretrainedModelsRoot).toBe(
			path.join(portableRoot, "packages", "pretrained-models", "support-v1"),
		);
		expect(paths.userDataDir).toBe(path.join(portableRoot, "data"));
		expect(paths.exportsDir).toBe(path.join(portableRoot, "exports"));
	});
});
