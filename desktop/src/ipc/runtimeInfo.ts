import type { DistributionKind } from "../runtime/paths";

export interface ElectronRuntimeInfo {
	runtime: "electron";
	distributionKind: DistributionKind;
	backendOrigin: string;
}

export function buildElectronRuntimeInfo(options: {
	distributionKind: DistributionKind;
	backendOrigin: string;
}): ElectronRuntimeInfo {
	return {
		runtime: "electron",
		distributionKind: options.distributionKind,
		backendOrigin: options.backendOrigin,
	};
}
