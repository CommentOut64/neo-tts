import path from "node:path";

import { describe, expect, it } from "vitest";

import type { ProductPaths } from "../src/runtime/paths";
import { buildDefaultBackendOptions } from "../src/backend/process";

function createProductPaths(distributionKind: "installed" | "portable"): ProductPaths {
  const runtimeRoot =
    distributionKind === "installed" ? "F:/NeoTTS" : "F:/NeoTTS-Portable";
  const resourcesDir = path.join(runtimeRoot, "resources", "app-runtime");
  const userDataDir =
    distributionKind === "installed"
      ? "C:/Users/wgh/AppData/Local/NeoTTS"
      : path.join(runtimeRoot, "data");
  const exportsDir =
    distributionKind === "installed"
      ? "C:/Users/wgh/Documents/NeoTTS/Exports"
      : path.join(runtimeRoot, "exports");

  return {
    distributionKind,
    runtimeRoot,
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

describe("backend process options", () => {
  it("starts installed flavor backend with appdata paths", () => {
    const paths = createProductPaths("installed");

    const options = buildDefaultBackendOptions(paths);

    expect(options.pythonExecutable).toBe(paths.runtimePython);
    expect(options.workingDirectory).toBe(paths.resourcesDir);
    expect(options.args).toEqual([
      "-m",
      "backend.app.cli",
      "--host",
      "127.0.0.1",
      "--port",
      "18600",
    ]);
    expect(options.environment?.NEO_TTS_DISTRIBUTION_KIND).toBe("installed");
    expect(options.environment?.NEO_TTS_PROJECT_ROOT).toBe(paths.runtimeRoot);
    expect(options.environment?.NEO_TTS_RESOURCES_ROOT).toBe(paths.resourcesDir);
    expect(options.environment?.NEO_TTS_USER_DATA_ROOT).toBe(paths.userDataDir);
    expect(options.environment?.NEO_TTS_EXPORTS_ROOT).toBe(paths.exportsDir);
    expect(options.environment?.NEO_TTS_LOGS_ROOT).toBe(paths.logsDir);
    expect(options.environment?.PYTHONPATH).toContain(paths.resourcesDir);
    expect(options.environment?.PYTHONPATH).toContain(paths.gptSovitsDir);
    expect(options.healthTimeoutMs).toBeGreaterThanOrEqual(30_000);
  });

  it("starts portable flavor backend with side-by-side data paths", () => {
    const paths = createProductPaths("portable");

    const options = buildDefaultBackendOptions(paths);

    expect(options.pythonExecutable).toBe(paths.runtimePython);
    expect(options.workingDirectory).toBe(paths.resourcesDir);
    expect(options.environment?.NEO_TTS_DISTRIBUTION_KIND).toBe("portable");
    expect(options.environment?.NEO_TTS_USER_DATA_ROOT).toBe(paths.userDataDir);
    expect(options.environment?.NEO_TTS_EXPORTS_ROOT).toBe(paths.exportsDir);
    expect(options.environment?.PYTHONPATH).toContain(paths.resourcesDir);
    expect(options.environment?.PYTHONPATH).toContain(paths.gptSovitsDir);
    expect(options.healthTimeoutMs).toBeGreaterThanOrEqual(30_000);
  });
});
