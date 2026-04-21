import { openFileDialog } from "@/api/system";

type ElectronFileSelectionBridge = {
  runtime: "electron";
  getPathForFile(file: File): string | null;
};

function getElectronFileSelectionBridge(): ElectronFileSelectionBridge | null {
  if (typeof window === "undefined") {
    return null;
  }

  const bridge = window.neoTTS;
  if (!bridge || bridge.runtime !== "electron") {
    return null;
  }
  if (typeof bridge.getPathForFile !== "function") {
    return null;
  }
  return bridge;
}

export function supportsNativeFilePathBridge(): boolean {
  return getElectronFileSelectionBridge() !== null;
}

export function resolveAbsolutePathForFile(file: File): string | null {
  const bridge = getElectronFileSelectionBridge();
  if (bridge === null) {
    return null;
  }
  const rawPath = bridge.getPathForFile(file);
  if (typeof rawPath !== "string" || rawPath.trim().length === 0) {
    return null;
  }
  return rawPath;
}

function extractFileName(rawPath: string): string {
  const segments = rawPath.split(/[/\\]/);
  return segments[segments.length - 1] || rawPath;
}

export async function selectAbsolutePathForFile(input: {
  accept: string;
  initialDir?: string;
}): Promise<{ name: string; absolutePath: string } | null> {
  const absolutePath = await openFileDialog(input.accept, input.initialDir);
  if (!absolutePath) {
    return null;
  }
  return {
    name: extractFileName(absolutePath),
    absolutePath,
  };
}
