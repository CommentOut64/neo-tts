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
  const pretrainedModelsDir = path.join(resourcesDir, "pretrained_models");
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
    appCoreRoot: resourcesDir,
    modelsRoot: resourcesDir,
    pretrainedModelsRoot: resourcesDir,
    resourcesDir,
    backendDir: path.join(resourcesDir, "backend"),
    frontendDir: path.join(resourcesDir, "frontend-dist"),
    gptSovitsDir: path.join(resourcesDir, "GPT_SoVITS"),
    runtimePython: path.join(resourcesDir, "runtime", "python", "python.exe"),
    builtinModelDir: path.join(resourcesDir, "models", "builtin"),
    pretrainedModelsDir,
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
    expect(options.environment?.SV_MODEL_PATH).toBe(
      path.join(paths.pretrainedModelsDir, "sv", "pretrained_eres2netv2w24s4ep4.ckpt"),
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
    expect(options.environment?.SV_MODEL_PATH).toBe(
      path.join(paths.pretrainedModelsDir, "sv", "pretrained_eres2netv2w24s4ep4.ckpt"),
    );
    expect(options.environment?.NLTK_DATA).toBe(nltkDataDir);
    expect(options.environment?.PATH?.startsWith(runtimePythonDir)).toBe(true);
    expect(options.environment?.PYTHONPATH).toContain(paths.resourcesDir);
    expect(options.environment?.PYTHONPATH).toContain(paths.gptSovitsDir);
    expect(options.healthTimeoutMs).toBe(40_000);
  });

  it("isolates packaged backend from host Python environment pollution", () => {
    const originalPythonPath = process.env.PYTHONPATH;
    const originalPath = process.env.PATH;
    const originalPythonHome = process.env.PYTHONHOME;
    const originalPythonUserBase = process.env.PYTHONUSERBASE;
    const originalOwnerOrigin = process.env.NEO_TTS_OWNER_CONTROL_ORIGIN;
    const originalOwnerToken = process.env.NEO_TTS_OWNER_CONTROL_TOKEN;
    const originalOwnerSessionId = process.env.NEO_TTS_OWNER_SESSION_ID;
    const originalBootstrapOrigin = process.env.NEO_TTS_BOOTSTRAP_CONTROL_ORIGIN;
    const originalBootstrapApiVersion = process.env.NEO_TTS_BOOTSTRAP_API_VERSION;

    try {
      process.env.PYTHONPATH = "C:/Users/wgh/AppData/Roaming/Python/Python311/site-packages";
      process.env.PATH = [
        "C:/Users/wgh/AppData/Roaming/Python/Python311/Scripts",
        "C:/Users/wgh/AppData/Roaming/Python/Python311",
      ].join(path.delimiter);
      process.env.PYTHONHOME = "C:/host-python";
      process.env.PYTHONUSERBASE = "C:/Users/wgh/AppData/Roaming/Python";
      process.env.NEO_TTS_OWNER_CONTROL_ORIGIN = "http://127.0.0.1:43125";
      process.env.NEO_TTS_OWNER_CONTROL_TOKEN = "owner-token";
      process.env.NEO_TTS_OWNER_SESSION_ID = "session-1";
      process.env.NEO_TTS_BOOTSTRAP_CONTROL_ORIGIN = "http://127.0.0.1:43126";
      process.env.NEO_TTS_BOOTSTRAP_API_VERSION = "1";

      const paths = createProductPaths("portable");
      const options = buildDefaultBackendOptions(paths);
      const runtimePythonDir = path.dirname(paths.runtimePython);

      expect(options.environment?.PYTHONNOUSERSITE).toBe("1");
      expect(options.environment?.PYTHONHOME).toBeUndefined();
      expect(options.environment?.PYTHONUSERBASE).toBeUndefined();
      expect(options.environment?.PYTHONPATH?.split(path.delimiter)).toEqual([
        paths.resourcesDir,
        paths.gptSovitsDir,
      ]);
      expect(options.environment?.PATH?.split(path.delimiter)).not.toContain(
        "C:/Users/wgh/AppData/Roaming/Python/Python311",
      );
      expect(options.environment?.PATH?.split(path.delimiter)[0]).toBe(runtimePythonDir);
      expect(options.environment?.NEO_TTS_OWNER_CONTROL_ORIGIN).toBe(
        "http://127.0.0.1:43125",
      );
      expect(options.environment?.NEO_TTS_OWNER_CONTROL_TOKEN).toBe("owner-token");
      expect(options.environment?.NEO_TTS_OWNER_SESSION_ID).toBe("session-1");
      expect(options.environment?.NEO_TTS_BOOTSTRAP_CONTROL_ORIGIN).toBe(
        "http://127.0.0.1:43126",
      );
      expect(options.environment?.NEO_TTS_BOOTSTRAP_API_VERSION).toBe("1");
    } finally {
      restoreEnvValue("PYTHONPATH", originalPythonPath);
      restoreEnvValue("PATH", originalPath);
      restoreEnvValue("PYTHONHOME", originalPythonHome);
      restoreEnvValue("PYTHONUSERBASE", originalPythonUserBase);
      restoreEnvValue("NEO_TTS_OWNER_CONTROL_ORIGIN", originalOwnerOrigin);
      restoreEnvValue("NEO_TTS_OWNER_CONTROL_TOKEN", originalOwnerToken);
      restoreEnvValue("NEO_TTS_OWNER_SESSION_ID", originalOwnerSessionId);
      restoreEnvValue("NEO_TTS_BOOTSTRAP_CONTROL_ORIGIN", originalBootstrapOrigin);
      restoreEnvValue("NEO_TTS_BOOTSTRAP_API_VERSION", originalBootstrapApiVersion);
    }
  });

  it("passes packaged backend control overrides without path overrides", () => {
    const originalWatchdogEnabled = process.env.NEO_TTS_STDIN_WATCHDOG_ENABLED;
    const originalPreloadOnStart = process.env.GPT_SOVITS_PRELOAD_ON_START;
    const originalPreloadVoices = process.env.GPT_SOVITS_PRELOAD_VOICES;
    const originalGpuOffloadEnabled = process.env.GPT_SOVITS_GPU_OFFLOAD_ENABLED;
    const originalGpuMinFreeMb = process.env.GPT_SOVITS_GPU_MIN_FREE_MB;
    const originalGpuReserveMb = process.env.GPT_SOVITS_GPU_RESERVE_MB_FOR_LOAD;
    const originalStagingTtl = process.env.GPT_SOVITS_EDIT_SESSION_STAGING_TTL_SECONDS;
    const originalShortEnglish = process.env.GPT_SOVITS_PREPEND_COMMA_TO_SHORT_ENGLISH;
    const originalVoicesConfig = process.env.GPT_SOVITS_VOICES_CONFIG;
    const originalManagedVoicesDir = process.env.GPT_SOVITS_MANAGED_VOICES_DIR;
    const originalG2pw = process.env.is_g2pw;

    try {
      process.env.NEO_TTS_STDIN_WATCHDOG_ENABLED = "1";
      process.env.GPT_SOVITS_PRELOAD_ON_START = "1";
      process.env.GPT_SOVITS_PRELOAD_VOICES = "neuro2,custom";
      process.env.GPT_SOVITS_GPU_OFFLOAD_ENABLED = "0";
      process.env.GPT_SOVITS_GPU_MIN_FREE_MB = "1024";
      process.env.GPT_SOVITS_GPU_RESERVE_MB_FOR_LOAD = "2048";
      process.env.GPT_SOVITS_EDIT_SESSION_STAGING_TTL_SECONDS = "7200";
      process.env.GPT_SOVITS_PREPEND_COMMA_TO_SHORT_ENGLISH = "1";
      process.env.GPT_SOVITS_VOICES_CONFIG = "C:/host/config/voices.json";
      process.env.GPT_SOVITS_MANAGED_VOICES_DIR = "C:/host/managed_voices";
      process.env.is_g2pw = "1";

      const options = buildDefaultBackendOptions(createProductPaths("portable"));

      expect(options.environment?.NEO_TTS_STDIN_WATCHDOG_ENABLED).toBe("1");
      expect(options.environment?.GPT_SOVITS_PRELOAD_ON_START).toBe("1");
      expect(options.environment?.GPT_SOVITS_PRELOAD_VOICES).toBe("neuro2,custom");
      expect(options.environment?.GPT_SOVITS_GPU_OFFLOAD_ENABLED).toBe("0");
      expect(options.environment?.GPT_SOVITS_GPU_MIN_FREE_MB).toBe("1024");
      expect(options.environment?.GPT_SOVITS_GPU_RESERVE_MB_FOR_LOAD).toBe("2048");
      expect(options.environment?.GPT_SOVITS_EDIT_SESSION_STAGING_TTL_SECONDS).toBe("7200");
      expect(options.environment?.GPT_SOVITS_PREPEND_COMMA_TO_SHORT_ENGLISH).toBe("1");
      expect(options.environment?.GPT_SOVITS_VOICES_CONFIG).toBeUndefined();
      expect(options.environment?.GPT_SOVITS_MANAGED_VOICES_DIR).toBeUndefined();
      expect(options.environment?.is_g2pw).toBeUndefined();
    } finally {
      restoreEnvValue("NEO_TTS_STDIN_WATCHDOG_ENABLED", originalWatchdogEnabled);
      restoreEnvValue("GPT_SOVITS_PRELOAD_ON_START", originalPreloadOnStart);
      restoreEnvValue("GPT_SOVITS_PRELOAD_VOICES", originalPreloadVoices);
      restoreEnvValue("GPT_SOVITS_GPU_OFFLOAD_ENABLED", originalGpuOffloadEnabled);
      restoreEnvValue("GPT_SOVITS_GPU_MIN_FREE_MB", originalGpuMinFreeMb);
      restoreEnvValue("GPT_SOVITS_GPU_RESERVE_MB_FOR_LOAD", originalGpuReserveMb);
      restoreEnvValue("GPT_SOVITS_EDIT_SESSION_STAGING_TTL_SECONDS", originalStagingTtl);
      restoreEnvValue("GPT_SOVITS_PREPEND_COMMA_TO_SHORT_ENGLISH", originalShortEnglish);
      restoreEnvValue("GPT_SOVITS_VOICES_CONFIG", originalVoicesConfig);
      restoreEnvValue("GPT_SOVITS_MANAGED_VOICES_DIR", originalManagedVoicesDir);
      restoreEnvValue("is_g2pw", originalG2pw);
    }
  });
});

function restoreEnvValue(name: string, value: string | undefined): void {
  if (value === undefined) {
    delete process.env[name];
    return;
  }
  process.env[name] = value;
}
