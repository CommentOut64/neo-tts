import path from "node:path";

import { describe, expect, it } from "vitest";

import type { ProductPaths } from "../src/runtime/paths";
import {
  buildDefaultBackendOptions,
  formatBackendMonitorSample,
  parsePortOccupierPids,
  parseNvidiaSmiComputeAppsMemoryMiB,
  sampleWindowsBackendProcess,
} from "../src/backend/process";

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
  it("keeps source-tree development startup timeout at 30 seconds", () => {
    const options = buildDefaultBackendOptions("F:/neo-tts");

    expect(options.healthTimeoutMs).toBe(30_000);
  });

  it("parses netstat port occupiers regardless of localized state labels", () => {
    const output = [
      "  TCP    127.0.0.1:18600        0.0.0.0:0              LISTENING       1234",
      "  TCP    [::]:18600             [::]:0                 侦听             5678",
      "  TCP    127.0.0.1:51767        127.0.0.1:18600        ESTABLISHED     9999",
      "  TCP    127.0.0.1:18601        0.0.0.0:0              LISTENING       2222",
    ].join("\n");

    const occupiers = parsePortOccupierPids(output, 18600, { selfPid: 5678 });

    expect(occupiers).toEqual([1234]);
  });

  it("parses nvidia-smi compute apps csv and sums target pid memory", () => {
    const csv = [
      "1234, 2048",
      "4321, 512",
      "1234, 256",
    ].join("\n");

    expect(parseNvidiaSmiComputeAppsMemoryMiB(csv, 1234)).toBe(2304);
    expect(parseNvidiaSmiComputeAppsMemoryMiB(csv, 9999)).toBeNull();
  });

  it("samples backend process monitor info through injected command runner", () => {
    const sample = sampleWindowsBackendProcess(2468, {
      now: () => new Date("2026-04-19T04:00:00.000Z"),
      runCommand(command) {
        if (command.includes("Get-Process")) {
          return JSON.stringify({
            Id: 2468,
            CPU: 12.5,
            WorkingSet64: 268435456,
            ThreadCount: 9,
          });
        }
        if (command.includes("nvidia-smi")) {
          return "2468, 1024\n";
        }
        throw new Error(`unexpected command: ${command}`);
      },
    });

    expect(sample).toEqual({
      pid: 2468,
      cpuSeconds: 12.5,
      workingSetMb: 256,
      threadCount: 9,
      gpuMemoryMb: 1024,
      sampledAt: "2026-04-19T04:00:00.000Z",
    });
  });

  it("formats backend monitor samples into compact runtime log lines", () => {
    const line = formatBackendMonitorSample({
      pid: 2468,
      cpuSeconds: 12.5,
      workingSetMb: 256,
      threadCount: 9,
      gpuMemoryMb: 1024,
      sampledAt: "2026-04-19T04:00:00.000Z",
    });

    expect(line).toBe(
      "pid=2468 rss_mb=256.0 cpu_s=12.5 threads=9 gpu_mb=1024 sampled_at=2026-04-19T04:00:00.000Z",
    );
  });

  it("starts installed flavor backend with appdata paths", () => {
    const paths = createProductPaths("installed");

    const options = buildDefaultBackendOptions(paths);
    const runtimePythonDir = path.dirname(paths.runtimePython);
    const nltkDataDir = path.join(paths.resourcesDir, "runtime", "python", "nltk_data");

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
    expect(options.environment?.CNHUBERT_PATH).toBe(
      path.join(paths.builtinModelDir, "chinese-hubert-base"),
    );
    expect(options.environment?.GPT_SOVITS_CNHUBERT_PATH).toBe(
      path.join(paths.builtinModelDir, "chinese-hubert-base"),
    );
    expect(options.environment?.cnhubert_base_path).toBe(
      path.join(paths.builtinModelDir, "chinese-hubert-base"),
    );
    expect(options.environment?.BERT_PATH).toBe(
      path.join(paths.builtinModelDir, "chinese-roberta-wwm-ext-large"),
    );
    expect(options.environment?.GPT_SOVITS_BERT_PATH).toBe(
      path.join(paths.builtinModelDir, "chinese-roberta-wwm-ext-large"),
    );
    expect(options.environment?.bert_path).toBe(
      path.join(paths.builtinModelDir, "chinese-roberta-wwm-ext-large"),
    );
    expect(options.environment?.NLTK_DATA).toBe(nltkDataDir);
    expect(options.environment?.PATH?.startsWith(runtimePythonDir)).toBe(true);
    expect(options.environment?.PYTHONPATH).toContain(paths.resourcesDir);
    expect(options.environment?.PYTHONPATH).toContain(paths.gptSovitsDir);
    expect(options.healthTimeoutMs).toBe(40_000);
  });

  it("starts portable flavor backend with side-by-side data paths", () => {
    const paths = createProductPaths("portable");

    const options = buildDefaultBackendOptions(paths);
    const runtimePythonDir = path.dirname(paths.runtimePython);
    const nltkDataDir = path.join(paths.resourcesDir, "runtime", "python", "nltk_data");

    expect(options.pythonExecutable).toBe(paths.runtimePython);
    expect(options.workingDirectory).toBe(paths.resourcesDir);
    expect(options.environment?.NEO_TTS_DISTRIBUTION_KIND).toBe("portable");
    expect(options.environment?.NEO_TTS_USER_DATA_ROOT).toBe(paths.userDataDir);
    expect(options.environment?.NEO_TTS_EXPORTS_ROOT).toBe(paths.exportsDir);
    expect(options.environment?.CNHUBERT_PATH).toBe(
      path.join(paths.builtinModelDir, "chinese-hubert-base"),
    );
    expect(options.environment?.GPT_SOVITS_CNHUBERT_PATH).toBe(
      path.join(paths.builtinModelDir, "chinese-hubert-base"),
    );
    expect(options.environment?.cnhubert_base_path).toBe(
      path.join(paths.builtinModelDir, "chinese-hubert-base"),
    );
    expect(options.environment?.BERT_PATH).toBe(
      path.join(paths.builtinModelDir, "chinese-roberta-wwm-ext-large"),
    );
    expect(options.environment?.GPT_SOVITS_BERT_PATH).toBe(
      path.join(paths.builtinModelDir, "chinese-roberta-wwm-ext-large"),
    );
    expect(options.environment?.bert_path).toBe(
      path.join(paths.builtinModelDir, "chinese-roberta-wwm-ext-large"),
    );
    expect(options.environment?.NLTK_DATA).toBe(nltkDataDir);
    expect(options.environment?.PATH?.startsWith(runtimePythonDir)).toBe(true);
    expect(options.environment?.PYTHONPATH).toContain(paths.resourcesDir);
    expect(options.environment?.PYTHONPATH).toContain(paths.gptSovitsDir);
    expect(options.healthTimeoutMs).toBe(40_000);
  });
});
