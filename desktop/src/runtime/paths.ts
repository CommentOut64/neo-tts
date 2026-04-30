import fs from "node:fs";
import path from "node:path";
import process from "node:process";

import {
	readRuntimeDescriptor,
	resolveRuntimeDescriptorPath,
	type RuntimePackageKey,
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
	adapterSystemRoot: string;
	supportAssetsRoot: string;
	seedModelPackagesRoot: string;
	resourcesDir: string;
	backendDir: string;
	frontendDir: string;
	gptSovitsDir: string;
	runtimePython: string;
	builtinModelDir: string;
	pretrainedModelsDir: string;
	configDir: string;
	userDataDir: string;
	configDataDir: string;
	ttsRegistryDir: string;
	cacheDir: string;
	logsDir: string;
	exportsDir: string;
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
		adapterSystemRoot: appCoreRoot,
		supportAssetsRoot: appCoreRoot,
		seedModelPackagesRoot: appCoreRoot,
		userDataDir,
		exportsDir,
		gptSovitsDir: path.join(appCoreRoot, "GPT_SoVITS"),
		builtinModelDir: path.join(appCoreRoot, "models", "builtin"),
		pretrainedModelsDir: path.join(appCoreRoot, "pretrained_models"),
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
		bootstrapRoot: resolveDescriptorPackageRoot(
			productRoot,
			options.descriptor,
			"bootstrap",
		),
		updateAgentRoot: resolveDescriptorPackageRoot(
			productRoot,
			options.descriptor,
			"update-agent",
		),
		shellRoot: resolveDescriptorPackageRoot(productRoot, options.descriptor, "shell"),
		appCoreRoot: resolveDescriptorPackageRoot(productRoot, options.descriptor, "app-core"),
		runtimeRoot: resolveDescriptorPackageRoot(productRoot, options.descriptor, "python-runtime"),
		adapterSystemRoot: resolveDescriptorPackageRoot(productRoot, options.descriptor, "adapter-system"),
		supportAssetsRoot: resolveDescriptorPackageRoot(productRoot, options.descriptor, "support-assets"),
		seedModelPackagesRoot: resolveDescriptorPackageRoot(
			productRoot,
			options.descriptor,
			"seed-model-packages",
		),
		userDataDir: resolveDescriptorPath(productRoot, options.descriptor.paths.userDataRoot),
		exportsDir: resolveDescriptorPath(productRoot, options.descriptor.paths.exportsRoot),
		configDataDir: resolveDescriptorPath(
			productRoot,
			options.descriptor.paths.configRoot ?? options.descriptor.paths.userDataRoot,
		),
		ttsRegistryDir: resolveDescriptorPath(
			productRoot,
			options.descriptor.paths.ttsRegistryRoot ?? path.join(options.descriptor.paths.userDataRoot, "tts-registry"),
		),
		cacheDir: resolveDescriptorPath(
			productRoot,
			options.descriptor.paths.cacheRoot ?? path.join(options.descriptor.paths.userDataRoot, "cache"),
		),
		logsDir: resolveDescriptorPath(
			productRoot,
			options.descriptor.paths.logsRoot ?? path.join(options.descriptor.paths.userDataRoot, "logs"),
		),
	});
}

function resolveDescriptorPackageRoot(
	productRoot: string,
	descriptor: RuntimeDescriptor,
	packageKey: RuntimePackageKey,
): string {
	const packageState = descriptor.packages[packageKey];
	const configuredRoot = packageState.root?.trim();
	if (configuredRoot) {
		return resolveDescriptorPath(productRoot, configuredRoot);
	}

	const version = packageState.version?.trim();
	if (version) {
		return path.join(productRoot, "packages", packageKey, version);
	}

	throw new Error(`runtime descriptor package "${packageKey}" is missing both root and version`);
}

function resolveDescriptorPath(productRoot: string, configuredPath: string): string {
	const trimmedPath = configuredPath.trim();
	if (!trimmedPath) {
		throw new Error("runtime descriptor contains an empty path value");
	}
	return path.resolve(productRoot, trimmedPath);
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
	adapterSystemRoot: string;
	supportAssetsRoot: string;
	seedModelPackagesRoot: string;
	userDataDir: string;
	exportsDir: string;
	configDataDir?: string;
	ttsRegistryDir?: string;
	cacheDir?: string;
	logsDir?: string;
	gptSovitsDir?: string;
	builtinModelDir?: string;
	pretrainedModelsDir?: string;
}): ProductPaths {
	const productRoot = path.resolve(options.productRoot);
	const bootstrapRoot = path.resolve(options.bootstrapRoot);
	const updateAgentRoot = path.resolve(options.updateAgentRoot);
	const shellRoot = path.resolve(options.shellRoot);
	const appCoreRoot = path.resolve(options.appCoreRoot);
	const runtimeRoot = path.resolve(options.runtimeRoot);
	const adapterSystemRoot = path.resolve(options.adapterSystemRoot);
	const supportAssetsRoot = path.resolve(options.supportAssetsRoot);
	const seedModelPackagesRoot = path.resolve(options.seedModelPackagesRoot);
	const userDataDir = path.resolve(options.userDataDir);
	const exportsDir = path.resolve(options.exportsDir);
	const configDataDir = path.resolve(options.configDataDir ?? path.join(userDataDir, "config"));
	const ttsRegistryDir = path.resolve(options.ttsRegistryDir ?? path.join(userDataDir, "tts-registry"));
	const cacheDir = path.resolve(options.cacheDir ?? path.join(userDataDir, "cache"));
	const logsDir = path.resolve(options.logsDir ?? path.join(userDataDir, "logs"));
	const gptSovitsDir = path.resolve(
		options.gptSovitsDir ??
			path.join(adapterSystemRoot, "adapter-system", "gpt-sovits", "GPT_SoVITS"),
	);
	const builtinModelDir = path.resolve(
		options.builtinModelDir ??
			path.join(supportAssetsRoot, "support-assets", "gpt-sovits"),
	);
	const pretrainedModelsDir = path.resolve(
		options.pretrainedModelsDir ??
			path.join(supportAssetsRoot, "support-assets", "shared", "pretrained_models"),
	);

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
		adapterSystemRoot,
		supportAssetsRoot,
		seedModelPackagesRoot,
		resourcesDir: appCoreRoot,
		backendDir: path.join(appCoreRoot, "backend"),
		frontendDir: path.join(appCoreRoot, "frontend-dist"),
		gptSovitsDir,
		runtimePython: path.join(runtimeRoot, "runtime", "python", "python.exe"),
		builtinModelDir,
		pretrainedModelsDir,
		configDir: path.join(appCoreRoot, "config"),
		userDataDir,
		configDataDir,
		ttsRegistryDir,
		cacheDir,
		logsDir,
		exportsDir,
	};
}
