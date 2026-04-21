import fs from "node:fs";
import path from "node:path";
import process from "node:process";

import {
	readRuntimeDescriptor,
	resolveRuntimeDescriptorPath,
	type RuntimeDescriptor,
} from "./runtimeDescriptor";

export type DistributionKind = "installed" | "portable";
export type ProductPathResolutionKind =
	| "descriptor"
	| "development-fallback"
	| "missing-descriptor";

export interface ProductPaths {
	resolutionKind: ProductPathResolutionKind;
	runtimeDescriptorPath: string | null;
	distributionKind: DistributionKind;
	productRoot: string;
	bootstrapRoot: string;
	updateAgentRoot: string;
	shellRoot: string;
	appCoreRoot: string;
	runtimeRoot: string;
	modelsRoot: string;
	pretrainedModelsRoot: string;
	resourcesDir: string;
	backendDir: string;
	frontendDir: string;
	gptSovitsDir: string;
	runtimePython: string;
	builtinModelDir: string;
	pretrainedModelsDir: string;
	configDir: string;
	userDataDir: string;
	logsDir: string;
	exportsDir: string;
	userModelsDir: string;
}

export interface ResolveProductPathsOptions {
	appName: string;
	executablePath: string;
	resourcesPath: string;
	localAppDataPath: string;
	documentsPath: string;
	env?: NodeJS.ProcessEnv;
	mode?: "development" | "product";
}

const PORTABLE_FLAG_FILENAME = "portable.flag";

export function resolveProductPaths(
	options: ResolveProductPathsOptions,
): ProductPaths {
	const productRoot = path.dirname(path.resolve(options.executablePath));
	const distributionKind = detectDistributionKind(productRoot);
	const descriptorResolution = resolveRuntimeDescriptorPath({
		productRoot,
		env: options.env ?? process.env,
	});

	if (descriptorResolution.descriptorPath !== null) {
		return buildDescriptorProductPaths({
			descriptorPath: descriptorResolution.descriptorPath,
			descriptor: readRuntimeDescriptor(descriptorResolution.descriptorPath),
		});
	}

	return buildLegacyFallbackProductPaths({
		resolutionKind:
			(options.mode ?? "product") === "development"
				? "development-fallback"
				: "missing-descriptor",
		distributionKind,
		productRoot,
		resourcesPath: options.resourcesPath,
		localAppDataPath: options.localAppDataPath,
		documentsPath: options.documentsPath,
		appName: options.appName,
	});
}

export function buildDefaultProductPaths(): ProductPaths {
	const localAppDataPath =
		process.env.LOCALAPPDATA ??
		path.join(
			process.env.USERPROFILE ?? path.dirname(process.execPath),
			"AppData",
			"Local",
		);
	const documentsPath =
		process.env.USERPROFILE !== undefined
			? path.join(process.env.USERPROFILE, "Documents")
			: path.dirname(process.execPath);

	return resolveProductPaths({
		appName: "NeoTTS",
		executablePath: process.execPath,
		resourcesPath: process.resourcesPath,
		localAppDataPath,
		documentsPath,
		env: process.env,
		mode: "product",
	});
}

function detectDistributionKind(runtimeRoot: string): DistributionKind {
	return fs.existsSync(path.join(runtimeRoot, PORTABLE_FLAG_FILENAME))
		? "portable"
		: "installed";
}

function buildLegacyFallbackProductPaths(options: {
	resolutionKind: ProductPathResolutionKind;
	distributionKind: DistributionKind;
	productRoot: string;
	resourcesPath: string;
	localAppDataPath: string;
	documentsPath: string;
	appName: string;
}): ProductPaths {
	const appCoreRoot = path.join(path.resolve(options.resourcesPath), "app-runtime");
	const userDataDir =
		options.distributionKind === "portable"
			? path.join(options.productRoot, "data")
			: path.join(path.resolve(options.localAppDataPath), options.appName);
	const exportsDir =
		options.distributionKind === "portable"
			? path.join(options.productRoot, "exports")
			: path.join(path.resolve(options.documentsPath), options.appName, "Exports");

	return buildProductPaths({
		resolutionKind: options.resolutionKind,
		runtimeDescriptorPath: null,
		distributionKind: options.distributionKind,
		productRoot: options.productRoot,
		bootstrapRoot: options.productRoot,
		updateAgentRoot: options.productRoot,
		shellRoot: options.productRoot,
		appCoreRoot,
		runtimeRoot: appCoreRoot,
		modelsRoot: appCoreRoot,
		pretrainedModelsRoot: appCoreRoot,
		userDataDir,
		exportsDir,
	});
}

function buildDescriptorProductPaths(options: {
	descriptorPath: string;
	descriptor: RuntimeDescriptor;
}): ProductPaths {
	const productRoot = path.dirname(path.dirname(path.resolve(options.descriptorPath)));
	return buildProductPaths({
		resolutionKind: "descriptor",
		runtimeDescriptorPath: options.descriptorPath,
		distributionKind: options.descriptor.distributionKind,
		productRoot,
		bootstrapRoot: options.descriptor.packages.bootstrap.root,
		updateAgentRoot: options.descriptor.packages["update-agent"].root,
		shellRoot: options.descriptor.packages.shell.root,
		appCoreRoot: options.descriptor.packages["app-core"].root,
		runtimeRoot: options.descriptor.packages.runtime.root,
		modelsRoot: options.descriptor.packages.models.root,
		pretrainedModelsRoot: options.descriptor.packages["pretrained-models"].root,
		userDataDir: options.descriptor.paths.userDataRoot,
		exportsDir: options.descriptor.paths.exportsRoot,
	});
}

function buildProductPaths(options: {
	resolutionKind: ProductPathResolutionKind;
	runtimeDescriptorPath: string | null;
	distributionKind: DistributionKind;
	productRoot: string;
	bootstrapRoot: string;
	updateAgentRoot: string;
	shellRoot: string;
	appCoreRoot: string;
	runtimeRoot: string;
	modelsRoot: string;
	pretrainedModelsRoot: string;
	userDataDir: string;
	exportsDir: string;
}): ProductPaths {
	const productRoot = path.resolve(options.productRoot);
	const bootstrapRoot = path.resolve(options.bootstrapRoot);
	const updateAgentRoot = path.resolve(options.updateAgentRoot);
	const shellRoot = path.resolve(options.shellRoot);
	const appCoreRoot = path.resolve(options.appCoreRoot);
	const runtimeRoot = path.resolve(options.runtimeRoot);
	const modelsRoot = path.resolve(options.modelsRoot);
	const pretrainedModelsRoot = path.resolve(options.pretrainedModelsRoot);
	const userDataDir = path.resolve(options.userDataDir);
	const exportsDir = path.resolve(options.exportsDir);

	return {
		resolutionKind: options.resolutionKind,
		runtimeDescriptorPath: options.runtimeDescriptorPath,
		distributionKind: options.distributionKind,
		productRoot,
		bootstrapRoot,
		updateAgentRoot,
		shellRoot,
		appCoreRoot,
		runtimeRoot,
		modelsRoot,
		pretrainedModelsRoot,
		resourcesDir: appCoreRoot,
		backendDir: path.join(appCoreRoot, "backend"),
		frontendDir: path.join(appCoreRoot, "frontend-dist"),
		gptSovitsDir: path.join(appCoreRoot, "GPT_SoVITS"),
		runtimePython: path.join(runtimeRoot, "runtime", "python", "python.exe"),
		builtinModelDir: path.join(modelsRoot, "models", "builtin"),
		pretrainedModelsDir: path.join(pretrainedModelsRoot, "pretrained_models"),
		configDir: path.join(appCoreRoot, "config"),
		userDataDir,
		logsDir: path.join(userDataDir, "logs"),
		exportsDir,
		userModelsDir: path.join(userDataDir, "models"),
	};
}
