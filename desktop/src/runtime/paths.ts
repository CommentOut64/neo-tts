import fs from "node:fs";
import path from "node:path";
import process from "node:process";

export type DistributionKind = "installed" | "portable";

export interface ProductPaths {
	distributionKind: DistributionKind;
	runtimeRoot: string;
	resourcesDir: string;
	backendDir: string;
	frontendDir: string;
	gptSovitsDir: string;
	runtimePython: string;
	builtinModelDir: string;
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
}

const PORTABLE_FLAG_FILENAME = "portable.flag";

export function resolveProductPaths(
	options: ResolveProductPathsOptions,
): ProductPaths {
	const runtimeRoot = path.dirname(path.resolve(options.executablePath));
	const distributionKind = detectDistributionKind(runtimeRoot);
	const resourcesDir = path.join(path.resolve(options.resourcesPath), "app-runtime");

	if (distributionKind === "portable") {
		const userDataDir = path.join(runtimeRoot, "data");
		return buildProductPaths({
			distributionKind,
			runtimeRoot,
			resourcesDir,
			userDataDir,
			exportsDir: path.join(runtimeRoot, "exports"),
		});
	}

	const userDataDir = path.join(path.resolve(options.localAppDataPath), options.appName);
	return buildProductPaths({
		distributionKind,
		runtimeRoot,
		resourcesDir,
		userDataDir,
		exportsDir: path.join(path.resolve(options.documentsPath), options.appName, "Exports"),
	});
}

export function buildDefaultProductPaths(): ProductPaths {
	const localAppDataPath =
		process.env.LOCALAPPDATA ?? path.join(process.env.USERPROFILE ?? path.dirname(process.execPath), "AppData", "Local");
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
	});
}

function detectDistributionKind(runtimeRoot: string): DistributionKind {
	return fs.existsSync(path.join(runtimeRoot, PORTABLE_FLAG_FILENAME))
		? "portable"
		: "installed";
}

function buildProductPaths(options: {
	distributionKind: DistributionKind;
	runtimeRoot: string;
	resourcesDir: string;
	userDataDir: string;
	exportsDir: string;
}): ProductPaths {
	const resourcesDir = path.resolve(options.resourcesDir);
	const userDataDir = path.resolve(options.userDataDir);
	const exportsDir = path.resolve(options.exportsDir);

	return {
		distributionKind: options.distributionKind,
		runtimeRoot: path.resolve(options.runtimeRoot),
		resourcesDir,
		backendDir: path.join(resourcesDir, "backend"),
		frontendDir: path.join(resourcesDir, "frontend-dist"),
		gptSovitsDir: path.join(resourcesDir, "GPT_SoVITS"),
		runtimePython: path.join(resourcesDir, "runtime", "python", "python.exe"),
		builtinModelDir: path.join(resourcesDir, "models", "builtin"),
		configDir: path.join(resourcesDir, "config"),
		userDataDir,
		logsDir: path.join(userDataDir, "logs"),
		exportsDir,
		userModelsDir: path.join(userDataDir, "models"),
	};
}
