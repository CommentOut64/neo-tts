import fs from "node:fs";
import path from "node:path";

import type { DistributionKind } from "./paths";

export const RUNTIME_DESCRIPTOR_ENV = "NEO_TTS_RUNTIME_DESCRIPTOR";

export type RuntimePackageKey =
	| "bootstrap"
	| "update-agent"
	| "shell"
	| "app-core"
	| "runtime"
	| "models"
	| "pretrained-models";

export interface RuntimeDescriptorPackage {
	version: string;
	root: string;
}

export interface RuntimeDescriptor {
	schemaVersion: number;
	distributionKind: DistributionKind;
	channel?: string;
	releaseId?: string;
	packages: Record<RuntimePackageKey, RuntimeDescriptorPackage>;
	paths: {
		userDataRoot: string;
		exportsRoot: string;
	};
}

export interface ResolveRuntimeDescriptorPathOptions {
	productRoot: string;
	env?: NodeJS.ProcessEnv;
}

export interface RuntimeDescriptorPathResolution {
	descriptorPath: string | null;
	source: "env" | "state-file" | null;
}

export function resolveRuntimeDescriptorPath(
	options: ResolveRuntimeDescriptorPathOptions,
): RuntimeDescriptorPathResolution {
	const fromEnv = options.env?.[RUNTIME_DESCRIPTOR_ENV]?.trim();
	if (fromEnv) {
		return {
			descriptorPath: path.resolve(fromEnv),
			source: "env",
		};
	}

	const fromState = path.join(path.resolve(options.productRoot), "state", "current.json");
	if (fs.existsSync(fromState)) {
		return {
			descriptorPath: fromState,
			source: "state-file",
		};
	}

	return {
		descriptorPath: null,
		source: null,
	};
}

export function readRuntimeDescriptor(descriptorPath: string): RuntimeDescriptor {
	return JSON.parse(fs.readFileSync(descriptorPath, "utf-8")) as RuntimeDescriptor;
}
