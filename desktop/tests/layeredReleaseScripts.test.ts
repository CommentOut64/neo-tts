import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";

describe("layered release scripts", () => {
  it("adds a dedicated layered release builder and manifest writer for the portable-first update packages", () => {
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
    expect(buildScript).toContain('"python-runtime"');
    expect(buildScript).toContain('"adapter-system"');
    expect(buildScript).toContain('"support-assets"');
    expect(buildScript).toContain('"seed-model-packages"');
  });

  it("renames the packaged Electron executable to NeoTTSApp.exe while integrated packaging still prepares NeoTTS.exe launcher entrypoints", () => {
    const electronBuilderPath = path.join(process.cwd(), "electron-builder.yml");
    const integratedPackagePath = path.join(process.cwd(), "scripts", "build-integrated-package.ps1");
    const portableAssemblyPath = path.join(process.cwd(), "scripts", "assemble-portable.ps1");
    const bootstrapBuildPath = path.join(process.cwd(), "..", "launcher", "build-bootstrap.ps1");
    const launcherBuildPath = path.join(process.cwd(), "..", "launcher", "build.ps1");

    const electronBuilder = readFileSync(electronBuilderPath, "utf-8");
    const integratedPackage = readFileSync(integratedPackagePath, "utf-8");
    const portableAssembly = readFileSync(portableAssemblyPath, "utf-8");
    const bootstrapBuild = readFileSync(bootstrapBuildPath, "utf-8");
    const launcherBuild = readFileSync(launcherBuildPath, "utf-8");

    expect(electronBuilder).toMatch(/executableName:\s*NeoTTSApp/);
    expect(integratedPackage).toContain("build-bootstrap.ps1");
    expect(integratedPackage).toContain("NeoTTSApp.exe");
    expect(integratedPackage).toContain("NeoTTSUpdateAgent.exe");
    expect(integratedPackage).toContain("NeoTTS.exe");
    expect(portableAssembly).toContain("NeoTTSApp.exe");
    expect(portableAssembly).toContain("NeoTTS.exe");
    expect(bootstrapBuild).toContain("-H windowsgui");
    expect(launcherBuild).toContain("-H windowsgui");
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
    expect(stageRuntime).toContain('"python-runtime"');
    expect(stageRuntime).toContain('"adapter-system"');
    expect(stageRuntime).toContain('"support-assets"');
    expect(stageRuntime).toContain('"seed-model-packages"');

    expect(integratedPackage).toContain("build-layered-release.ps1");

    expect(manifest).toContain('"layerPackage": "app-core"');
    expect(manifest).toContain('"layerPackage": "adapter-system"');
    expect(manifest).toContain('"layerPackage": "support-assets"');

    expect(profile).toContain('"layeredPackages"');
    expect(profile).toContain('"pythonRuntimeVersion"');
    expect(profile).toContain('"pythonRuntimeVersion": "py311-cu128-v1"');
    expect(profile).toContain('"adapterSystemVersion"');
    expect(profile).toContain('"supportAssetsVersion"');
    expect(profile).toContain('"seedModelPackagesVersion"');
    expect(stageRuntime).toContain("https://download.pytorch.org/whl/cu128");
    expect(stageRuntime).not.toContain("https://download.pytorch.org/whl/cu124");
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
    expect(offlineScript).toContain("BaselinePortableRoot");
    expect(offlineScript).toContain("Write-Utf8NoBomFile");
    expect(offlineScript).toContain("NoCompression");
    expect(offlineScript).not.toContain('Copy-Item -LiteralPath (Join-Path $layeredRootPath "channels")');
    expect(offlineScript).not.toContain('Copy-Item -LiteralPath (Join-Path $layeredRootPath "releases")');
    expect(offlineScript).not.toContain("Copy-Item -LiteralPath $packagesPath");

    const integratedPackage = readFileSync(integratedPackagePath, "utf-8");
    expect(integratedPackage).not.toContain("build-offline-update-package.ps1");

    const packageJson = readFileSync(packageJsonPath, "utf-8");
    expect(packageJson).not.toContain("build-offline-update-package.ps1");
  });

  it("builds a baseline-diff portable offline update package with generated UTF-8 latest metadata", () => {
    const tempRoot = mkdtempSync(path.join(os.tmpdir(), "neotts-offline-fixture-"));
    try {
      const layeredRoot = path.join(tempRoot, "release");
      const baselineRoot = path.join(tempRoot, "baseline");
      const outputRoot = path.join(tempRoot, "output");
      mkdirSync(path.join(layeredRoot, "releases", "v0.0.2"), { recursive: true });
      mkdirSync(path.join(layeredRoot, "packages", "bootstrap"), { recursive: true });
      mkdirSync(path.join(layeredRoot, "packages", "python-runtime"), { recursive: true });
      mkdirSync(path.join(baselineRoot, "state"), { recursive: true });
      mkdirSync(outputRoot, { recursive: true });

      writeFileSync(path.join(layeredRoot, "packages", "bootstrap", "0.0.2.zip"), "bootstrap-package");
      writeFileSync(path.join(layeredRoot, "packages", "python-runtime", "py311-cu128-v1.zip"), "runtime-package");
      const manifestPayload = JSON.stringify({
        schemaVersion: 1,
        releaseId: "v0.0.2",
        channel: "stable",
        releaseKind: "stable",
        packages: {
          bootstrap: { version: "0.0.2", sha256: "bootstrap", sizeBytes: 17 },
          "python-runtime": { version: "py311-cu128-v1", sha256: "runtime", sizeBytes: 15 },
        },
      });
      writeFileSync(
        path.join(layeredRoot, "releases", "v0.0.2", "manifest.json"),
        manifestPayload,
      );
      mkdirSync(path.join(layeredRoot, "channels", "stable"), { recursive: true });
      writeFileSync(
        path.join(layeredRoot, "channels", "stable", "latest.json"),
        Buffer.concat([
          Buffer.from([0xef, 0xbb, 0xbf]),
          Buffer.from(JSON.stringify({
          schemaVersion: 1,
          channel: "stable",
          releaseId: "v0.0.2",
          releaseKind: "stable",
          manifestUrl: "releases/v0.0.2/manifest.json",
          manifestSha256: createHash("sha256").update(manifestPayload).digest("hex"),
          minBootstrapVersion: "0.0.0",
          publishedAt: "2026-04-27T00:00:00.000Z",
        })),
        ]),
      );
      writeFileSync(
        path.join(baselineRoot, "state", "current.json"),
        JSON.stringify({
          schemaVersion: 1,
          distributionKind: "portable",
          releaseId: "v0.0.1",
          packages: {
            bootstrap: { version: "0.0.1" },
            "python-runtime": { version: "py311-cu128-v1" },
          },
        }),
      );

      execFileSync(
        "powershell",
        [
          "-NoProfile",
          "-ExecutionPolicy",
          "Bypass",
          "-File",
          path.join(process.cwd(), "scripts", "build-offline-update-package.ps1"),
          "-LayeredReleaseRoot",
          layeredRoot,
          "-ReleaseId",
          "v0.0.2",
          "-BaselinePortableRoot",
          baselineRoot,
          "-OutputRoot",
          outputRoot,
        ],
        { stdio: "pipe" },
      );

      const zipPath = path.join(outputRoot, "NeoTTS-Update-v0.0.2.zip");
      expect(existsSync(zipPath)).toBe(true);
      const inspection = execFileSync(
        "powershell",
        [
          "-NoProfile",
          "-Command",
          [
            "Add-Type -AssemblyName System.IO.Compression.FileSystem;",
            `$zip=[System.IO.Compression.ZipFile]::OpenRead('${zipPath.replace(/'/g, "''")}');`,
            "try {",
            "$zip.Entries | ForEach-Object { $_.FullName };",
            "$latest=$zip.GetEntry('channels/stable/latest.json');",
            "$stream=$latest.Open();",
            "try { $buffer=New-Object byte[] 3; $read=$stream.Read($buffer,0,3); \"LATEST_PREFIX=$([System.BitConverter]::ToString($buffer,0,$read))\" } finally { $stream.Dispose() }",
            "} finally { $zip.Dispose() }",
          ].join(" "),
        ],
        { encoding: "utf-8" },
      );

      expect(inspection).toContain("packages/bootstrap/0.0.2.zip");
      expect(inspection).not.toContain("packages/python-runtime/py311-cu128-v1.zip");
      expect(inspection).toContain("LATEST_PREFIX=7B");
      expect(inspection).not.toContain("LATEST_PREFIX=EF-BB-BF");
    } finally {
      rmSync(tempRoot, { recursive: true, force: true });
    }
  });

  it("adds an automated real portable offline update acceptance test entrypoint", () => {
    const acceptanceScriptPath = path.join(process.cwd(), "scripts", "test-portable-offline-update.ps1");
    const packageJsonPath = path.join(process.cwd(), "package.json");

    expect(existsSync(acceptanceScriptPath)).toBe(true);

    const acceptanceScript = readFileSync(acceptanceScriptPath, "utf-8");
    expect(acceptanceScript).toContain("BaselinePortableRoot");
    expect(acceptanceScript).toContain("LayeredReleaseRoot");
    expect(acceptanceScript).toContain("build-offline-update-package.ps1");
    expect(acceptanceScript).toContain("-BaselinePortableRoot $baselinePortablePath");
    expect(acceptanceScript).toContain("NeoTTS-Update-v");
    expect(acceptanceScript).toContain("pending-switch.json");
    expect(acceptanceScript).toContain("last-known-good.json");
    expect(acceptanceScript).toContain("cache\\offline-update\\inbox");
    expect(acceptanceScript).toContain("data\\logs");
    expect(acceptanceScript).toContain("Start-Process");

    const packageJson = readFileSync(packageJsonPath, "utf-8");
    expect(packageJson).toContain("test:portable-offline-update");
    expect(packageJson).toContain("test-portable-offline-update.ps1");
  });
});
