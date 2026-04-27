import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import {
	readRuntimeDescriptor,
	resolveRuntimeDescriptorPath,
	type RuntimeDescriptor,
} from "../src/runtime/runtimeDescriptor";

const tempDirs: string[] = [];

function createTempDir(prefix: string): string {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
	tempDirs.push(dir);
	return dir;
}

function buildDescriptor(rootDir: string, distributionKind: "installed" | "portable"): RuntimeDescriptor {
	return {
		schemaVersion: 1,
		distributionKind,
		channel: "stable",
		releaseId: "v0.0.1",
		packages: {
			bootstrap: {
				version: "1.1.0",
				root: path.join(rootDir, "packages", "bootstrap", "1.1.0"),
			},
			"update-agent": {
				version: "1.1.0",
				root: path.join(rootDir, "packages", "update-agent", "1.1.0"),
			},
			shell: {
				version: "v0.0.1",
				root: path.join(rootDir, "packages", "shell", "v0.0.1"),
			},
			"app-core": {
				version: "v0.0.1",
				root: path.join(rootDir, "packages", "app-core", "v0.0.1"),
			},
			runtime: {
				version: "py311-cu124-v1",
				root: path.join(rootDir, "packages", "runtime", "py311-cu124-v1"),
			},
			models: {
				version: "builtin-v1",
				root: path.join(rootDir, "packages", "models", "builtin-v1"),
			},
			"pretrained-models": {
				version: "support-v1",
				root: path.join(rootDir, "packages", "pretrained-models", "support-v1"),
			},
		},
		paths: {
			userDataRoot:
				distributionKind === "installed"
					? path.join(rootDir, "AppData", "Local", "NeoTTS")
					: path.join(rootDir, "data"),
			exportsRoot:
				distributionKind === "installed"
					? path.join(rootDir, "Documents", "NeoTTS", "Exports")
					: path.join(rootDir, "exports"),
		},
	};
}

function writeDescriptor(descriptorPath: string, descriptor: RuntimeDescriptor) {
	fs.mkdirSync(path.dirname(descriptorPath), { recursive: true });
	fs.writeFileSync(descriptorPath, JSON.stringify(descriptor, null, 2), "utf-8");
}

describe("runtime descriptor", () => {
	afterEach(() => {
		for (const dir of tempDirs.splice(0)) {
			fs.rmSync(dir, { recursive: true, force: true });
		}
	});

	it("reads current.json and preserves layered package roots", () => {
		const rootDir = createTempDir("neo-tts-runtime-descriptor-");
		const descriptorPath = path.join(rootDir, "state", "current.json");
		const descriptor = buildDescriptor(rootDir, "installed");
		writeDescriptor(descriptorPath, descriptor);

		const loaded = readRuntimeDescriptor(descriptorPath);

		expect(loaded).toEqual(descriptor);
	});

	it("prefers NEO_TTS_RUNTIME_DESCRIPTOR over bootstrap root state/current.json", () => {
		const runtimeRoot = createTempDir("neo-tts-runtime-root-");
		const envDescriptorPath = path.join(runtimeRoot, "external", "descriptor.json");
		const defaultDescriptorPath = path.join(runtimeRoot, "state", "current.json");

		writeDescriptor(envDescriptorPath, buildDescriptor(runtimeRoot, "portable"));
		writeDescriptor(defaultDescriptorPath, buildDescriptor(runtimeRoot, "installed"));

		const resolved = resolveRuntimeDescriptorPath({
			productRoot: runtimeRoot,
			env: {
				NEO_TTS_RUNTIME_DESCRIPTOR: envDescriptorPath,
			},
		});

		expect(resolved).toEqual({
			descriptorPath: envDescriptorPath,
			source: "env",
		});
	});
});
