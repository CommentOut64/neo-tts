import { resolveApiUrl } from "@/api/requestSupport";

export type RuntimeEnvironment = "web" | "electron";
export type DistributionKind = "installed" | "portable" | null;

interface ElectronRuntimeBridge {
  runtime: "electron";
  distributionKind: "installed" | "portable";
  backendOrigin: string;
  requestAppExit(): Promise<void>;
  openExternalUrl(url: string): Promise<void>;
}

export interface RuntimeConfig {
  runtime: RuntimeEnvironment;
  distributionKind: DistributionKind;
  backendOrigin: string;
}

function getElectronRuntimeBridge(): ElectronRuntimeBridge | null {
  if (typeof window === "undefined") {
    return null;
  }

  const bridge = window.neoTTS;
  if (!bridge || bridge.runtime !== "electron") {
    return null;
  }
  if (typeof bridge.requestAppExit !== "function") {
    return null;
  }
  if (bridge.distributionKind !== "installed" && bridge.distributionKind !== "portable") {
    return null;
  }
  if (typeof bridge.backendOrigin !== "string" || bridge.backendOrigin.length === 0) {
    return null;
  }
  return bridge;
}

export function getRuntimeConfig(): RuntimeConfig {
  const electronBridge = getElectronRuntimeBridge();
  if (electronBridge) {
    return {
      runtime: "electron",
      distributionKind: electronBridge.distributionKind,
      backendOrigin: electronBridge.backendOrigin,
    };
  }

  return {
    runtime: "web",
    distributionKind: null,
    backendOrigin: import.meta.env.VITE_API_BASE_URL || "",
  };
}

export function resolveBackendUrl(requestPath: string): string {
  return resolveApiUrl(requestPath, getRuntimeConfig().backendOrigin);
}
