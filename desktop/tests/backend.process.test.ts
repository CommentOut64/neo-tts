import path from "node:path";

import { describe, expect, it } from "vitest";

import type { ProductPaths } from "../src/runtime/paths";
import {
  buildDefaultBackendOptions,
  parsePortOccupierPids,
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
    expect(options.environment?.PYTHONPATH).toContain(paths.resourcesDir);
    expect(options.environment?.PYTHONPATH).toContain(paths.gptSovitsDir);
    expect(options.healthTimeoutMs).toBe(40_000);
  });

  it("starts portable flavor backend with side-by-side data paths", () => {
    const paths = createProductPaths("portable");

    const options = buildDefaultBackendOptions(paths);

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
    expect(options.environment?.PYTHONPATH).toContain(paths.resourcesDir);
    expect(options.environment?.PYTHONPATH).toContain(paths.gptSovitsDir);
    expect(options.healthTimeoutMs).toBe(40_000);
  });
});
