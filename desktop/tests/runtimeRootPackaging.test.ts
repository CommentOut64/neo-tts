import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

describe("runtime root packaging", () => {
  it("seeds portable roots with state/current.json and versioned package directories", () => {
    const portableFlavorPath = path.join(process.cwd(), "packaging", "flavors", "portable.v1.json");
    const portableAssemblyPath = path.join(process.cwd(), "scripts", "assemble-portable.ps1");

    const portableFlavor = readFileSync(portableFlavorPath, "utf-8");
    const portableAssembly = readFileSync(portableAssemblyPath, "utf-8");

    expect(portableFlavor).toContain('"stateRoot": "state"');
    expect(portableFlavor).toContain('"packagesRoot": "packages"');

    expect(portableAssembly).toContain("current.json");
    expect(portableAssembly).toContain('"bootstrap"');
    expect(portableAssembly).toContain('"update-agent"');
    expect(portableAssembly).toContain('"shell"');
    expect(portableAssembly).toContain('"app-core"');
    expect(portableAssembly).toContain('"runtime"');
    expect(portableAssembly).toContain('"models"');
    expect(portableAssembly).toContain('"pretrained-models"');
    expect(portableAssembly).toContain("packages");
    expect(portableAssembly).toContain("state");
  });

  it("switches installed packaging to per-user install roots and seeds state/packages before invoking Inno Setup", () => {
    const installedFlavorPath = path.join(process.cwd(), "packaging", "flavors", "installed.v1.json");
    const installerScriptPath = path.join(process.cwd(), "packaging", "installers", "windows-installer.iss");
    const integratedPackagePath = path.join(process.cwd(), "scripts", "build-integrated-package.ps1");

    const installedFlavor = readFileSync(installedFlavorPath, "utf-8");
    const installerScript = readFileSync(installerScriptPath, "utf-8");
    const integratedPackage = readFileSync(integratedPackagePath, "utf-8");

    expect(installedFlavor).toContain('"%LOCALAPPDATA%/Programs/NeoTTS"');

    expect(installerScript).toContain("DefaultDirName={localappdata}\\Programs\\{#AppName}");
    expect(installerScript).toContain("PrivilegesRequired=lowest");

    expect(integratedPackage).toContain("current.json");
    expect(integratedPackage).toContain("packages");
    expect(integratedPackage).toContain("NeoTTS-InstalledRoot");
    expect(integratedPackage).toContain("NeoTTSUpdateAgent.exe");
  });
});
