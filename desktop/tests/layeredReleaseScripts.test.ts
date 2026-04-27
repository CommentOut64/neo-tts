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

  it("adds a manually-triggered portable offline update package builder", () => {
    const offlineScriptPath = path.join(process.cwd(), "scripts", "build-offline-update-package.ps1");
    const integratedPackagePath = path.join(process.cwd(), "scripts", "build-integrated-package.ps1");
    const packageJsonPath = path.join(process.cwd(), "package.json");

    expect(existsSync(offlineScriptPath)).toBe(true);
    const offlineScript = readFileSync(offlineScriptPath, "utf-8");
    expect(offlineScript).toContain("NeoTTS-Update-v");
    expect(offlineScript).toContain("channels");
    expect(offlineScript).toContain("releases");
    expect(offlineScript).toContain("packages");
    expect(offlineScript).toContain('ValidateSet("portable")');
    expect(offlineScript).toContain("Load-JsonFile");
    expect(offlineScript).toContain("Get-FileSha256");
    expect(offlineScript).toContain("latest.releaseId");
    expect(offlineScript).toContain("manifest.releaseId");
    expect(offlineScript).toContain("manifestSha256");
    expect(offlineScript).toContain("PSObject.Properties");
    expect(offlineScript).not.toContain('Copy-Item -LiteralPath (Join-Path $layeredRootPath "channels")');
    expect(offlineScript).not.toContain('Copy-Item -LiteralPath (Join-Path $layeredRootPath "releases")');
    expect(offlineScript).not.toContain("Copy-Item -LiteralPath $packagesPath");

    const integratedPackage = readFileSync(integratedPackagePath, "utf-8");
    expect(integratedPackage).not.toContain("build-offline-update-package.ps1");

    const packageJson = readFileSync(packageJsonPath, "utf-8");
    expect(packageJson).not.toContain("build-offline-update-package.ps1");
  });

  it("adds an automated real portable offline update acceptance test entrypoint", () => {
    const acceptanceScriptPath = path.join(process.cwd(), "scripts", "test-portable-offline-update.ps1");
    const packageJsonPath = path.join(process.cwd(), "package.json");

    expect(existsSync(acceptanceScriptPath)).toBe(true);

    const acceptanceScript = readFileSync(acceptanceScriptPath, "utf-8");
    expect(acceptanceScript).toContain("BaselinePortableRoot");
    expect(acceptanceScript).toContain("LayeredReleaseRoot");
    expect(acceptanceScript).toContain("build-offline-update-package.ps1");
    expect(acceptanceScript).toContain("NeoTTS-Update-v");
    expect(acceptanceScript).toContain("pending-switch.json");
    expect(acceptanceScript).toContain("last-known-good.json");
    expect(acceptanceScript).toContain("cache\\offline-update\\inbox");
    expect(acceptanceScript).toContain("Start-Process");

    const packageJson = readFileSync(packageJsonPath, "utf-8");
    expect(packageJson).toContain("test:portable-offline-update");
    expect(packageJson).toContain("test-portable-offline-update.ps1");
  });
});
