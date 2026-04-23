import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

describe("layered release scripts", () => {
  it("adds a dedicated layered release builder and manifest writer for the seven update packages", () => {
    const buildScriptPath = path.join(process.cwd(), "scripts", "build-layered-release.ps1");
    const manifestWriterPath = path.join(process.cwd(), "scripts", "write-update-manifest.ps1");
    const policyPath = path.join(process.cwd(), "packaging", "update-package-policy.json");

    expect(existsSync(buildScriptPath)).toBe(true);
    expect(existsSync(manifestWriterPath)).toBe(true);
    expect(existsSync(policyPath)).toBe(true);

    const buildScript = readFileSync(buildScriptPath, "utf-8");
    expect(buildScript).toContain("update-package-policy.json");
    expect(buildScript).toContain("write-update-manifest.ps1");
    expect(buildScript).toContain('"bootstrap"');
    expect(buildScript).toContain('"update-agent"');
    expect(buildScript).toContain('"shell"');
    expect(buildScript).toContain('"app-core"');
    expect(buildScript).toContain('"runtime"');
    expect(buildScript).toContain('"models"');
    expect(buildScript).toContain('"pretrained-models"');
  });

  it("renames the packaged Electron executable to NeoTTSApp.exe while integrated packaging still prepares NeoTTS.exe launcher entrypoints", () => {
    const electronBuilderPath = path.join(process.cwd(), "electron-builder.yml");
    const integratedPackagePath = path.join(process.cwd(), "scripts", "build-integrated-package.ps1");
    const portableAssemblyPath = path.join(process.cwd(), "scripts", "assemble-portable.ps1");

    const electronBuilder = readFileSync(electronBuilderPath, "utf-8");
    const integratedPackage = readFileSync(integratedPackagePath, "utf-8");
    const portableAssembly = readFileSync(portableAssemblyPath, "utf-8");

    expect(electronBuilder).toMatch(/executableName:\s*NeoTTSApp/);
    expect(integratedPackage).toContain("build-bootstrap.ps1");
    expect(integratedPackage).toContain("NeoTTSApp.exe");
    expect(integratedPackage).toContain("NeoTTSUpdateAgent.exe");
    expect(integratedPackage).toContain("NeoTTS.exe");
    expect(portableAssembly).toContain("NeoTTSApp.exe");
    expect(portableAssembly).toContain("NeoTTS.exe");
  });

  it("records staged layer-package mapping metadata and version hints for reusable layered artifacts", () => {
    const stageRuntimePath = path.join(process.cwd(), "scripts", "stage-runtime.ps1");
    const integratedPackagePath = path.join(process.cwd(), "scripts", "build-integrated-package.ps1");
    const manifestPath = path.join(process.cwd(), "packaging", "manifests", "base.v1.json");
    const profilePath = path.join(process.cwd(), "packaging", "profiles", "default.v1.json");

    const stageRuntime = readFileSync(stageRuntimePath, "utf-8");
    const integratedPackage = readFileSync(integratedPackagePath, "utf-8");
    const manifest = readFileSync(manifestPath, "utf-8");
    const profile = readFileSync(profilePath, "utf-8");

    expect(stageRuntime).toContain("layerPackage");
    expect(stageRuntime).toContain('"app-core"');
    expect(stageRuntime).toContain('"runtime"');
    expect(stageRuntime).toContain('"models"');
    expect(stageRuntime).toContain('"pretrained-models"');

    expect(integratedPackage).toContain("build-layered-release.ps1");

    expect(manifest).toContain('"layerPackage": "app-core"');
    expect(manifest).toContain('"layerPackage": "models"');
    expect(manifest).toContain('"layerPackage": "pretrained-models"');

    expect(profile).toContain('"layeredPackages"');
    expect(profile).toContain('"runtimeVersion"');
    expect(profile).toContain('"modelsVersion"');
    expect(profile).toContain('"pretrainedModelsVersion"');
  });
});
