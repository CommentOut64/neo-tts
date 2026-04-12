import { prepareExit } from "@/api/system";

export interface RuntimeExitResult {
  launcherExitRequested: boolean;
}

export interface RuntimeHost {
  kind: "web" | "electron";
  requestExit(): Promise<RuntimeExitResult>;
}

type ElectronRuntimeBridge = {
  runtime: "electron";
  requestAppExit(): Promise<void>;
};

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
  return bridge;
}

export function getRuntimeHost(): RuntimeHost {
  const electronBridge = getElectronRuntimeBridge();
  if (electronBridge) {
    return {
      kind: "electron",
      async requestExit(): Promise<RuntimeExitResult> {
        await electronBridge.requestAppExit();
        return {
          launcherExitRequested: true,
        };
      },
    };
  }

  return {
    kind: "web",
    async requestExit(): Promise<RuntimeExitResult> {
      const result = await prepareExit();
      return {
        launcherExitRequested: result.launcher_exit_requested,
      };
    },
  };
}
