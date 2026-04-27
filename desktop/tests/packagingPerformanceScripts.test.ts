import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

describe("packaging performance scripts", () => {
  it("routes portable and layered zip creation through configurable 7-Zip", () => {
    const integrated = readFileSync(path.join(process.cwd(), "scripts", "build-integrated-package.ps1"), "utf-8");
    const layered = readFileSync(path.join(process.cwd(), "scripts", "build-layered-release.ps1"), "utf-8");
    const portable = readFileSync(path.join(process.cwd(), "scripts", "assemble-portable.ps1"), "utf-8");

    for (const source of [integrated, layered, portable]) {
      expect(source).toContain("$SevenZipPath");
      expect(source).toContain("C:\\Program Files\\7-Zip\\7z.exe");
    }
    for (const source of [layered, portable]) {
      expect(source).toContain("Resolve-SevenZipPath");
      expect(source).toContain("New-ZipArchiveWithSevenZip");
      expect(source).not.toContain("ZipFile]::CreateFromDirectory");
    }

    expect(integrated).toContain('"-SevenZipPath", $SevenZipPath');
    expect(integrated).toContain('"-ZipCompressionLevel", ([string]$ZipCompressionLevel)');
    expect(layered).toContain("-tzip");
    expect(layered).toContain('"-mx$CompressionLevel"');
    expect(portable).toContain("-tzip");
    expect(portable).toContain('"-mx$CompressionLevel"');
  });

  it("assembles portable package trees with hard links outside the zip body", () => {
    const portable = readFileSync(path.join(process.cwd(), "scripts", "assemble-portable.ps1"), "utf-8");

    expect(portable).toContain("Copy-PortableItem");
    expect(portable).toContain("-ItemType HardLink");
    expect(portable).toContain("Portable assembly hard link failed");
    expect(portable).toContain("Copy-DirectoryContents -SourcePath");
    expect(portable).not.toContain("Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $DestinationPath $_.Name) -Recurse -Force");
  });

  it("prints elapsed time and artifact size summaries for the integrated portable chain", () => {
    const integrated = readFileSync(path.join(process.cwd(), "scripts", "build-integrated-package.ps1"), "utf-8");

    expect(integrated).toContain("Invoke-TimedStep");
    expect(integrated).toContain("Write-ArtifactSizeSummary");
    expect(integrated).toContain("[build-integrated-package] Step timings:");
    expect(integrated).toContain("[build-integrated-package] Artifact size summary:");
    expect(integrated).toContain("$PortableRootPaths");
    expect(integrated).toContain("$PortableZipPaths");
    expect(integrated).toContain("Split-Path -Leaf $portableRootPath");
    expect(integrated).toContain("packages");
    expect(integrated).toContain("win-unpacked");
    expect(integrated).not.toContain('Join-Path $ReleaseRoot "NeoTTS-Portable"');
  });

  it("cleans win-unpacked by default after final package validation", () => {
    const integrated = readFileSync(path.join(process.cwd(), "scripts", "build-integrated-package.ps1"), "utf-8");

    expect(integrated).toContain("[switch]$KeepWinUnpacked");
    expect(integrated).toContain("Remove-WinUnpackedIfNeeded");
    expect(integrated).toContain('Invoke-TimedStep -Label "Clean win-unpacked"');
    expect(integrated).toContain("if ($KeepWinUnpacked)");
    expect(integrated).toContain("Remove-DirectoryIfExists -Path $winUnpackedRoot -AllowedRoot $releaseVersionRoot");
    expect(integrated).toContain("win-unpacked was cleaned");
  });

  it("cleans layered temporary workspace even when package archive creation fails", () => {
    const layered = readFileSync(path.join(process.cwd(), "scripts", "build-layered-release.ps1"), "utf-8");

    expect(layered).toContain("try {");
    expect(layered).toContain("finally {");
    expect(layered).toContain("Remove-PathIfExists -Path $temporaryRoot -AllowedRoot $releaseRootPath");
  });

  it("supports cu128 and cu118 portable runtime variants with isolated runtime artifacts", () => {
    const integrated = readFileSync(path.join(process.cwd(), "scripts", "build-integrated-package.ps1"), "utf-8");
    const stageRuntime = readFileSync(path.join(process.cwd(), "scripts", "stage-runtime.ps1"), "utf-8");
    const layered = readFileSync(path.join(process.cwd(), "scripts", "build-layered-release.ps1"), "utf-8");
    const portable = readFileSync(path.join(process.cwd(), "scripts", "assemble-portable.ps1"), "utf-8");
    const packageJson = readFileSync(path.join(process.cwd(), "package.json"), "utf-8");

    expect(integrated).toContain('[ValidateSet("cu128", "cu118")]');
    expect(integrated).toContain("[switch]$BuildCudaRuntimeVariants");
    expect(integrated).toContain("Invoke-CudaRuntimeVariantBuild");
    expect(integrated).toContain("NeoTTS-Portable-$packageVersion-$CudaRuntime.zip");
    expect(integrated).toContain("NeoTTS-Portable-$CudaRuntime");
    expect(integrated).toContain('Write-ArtifactSizeSummary -ReleaseRoot $releaseVersionRoot -PortableRootPaths @(');
    expect(integrated).toContain("-PortableZipPaths @(");
    expect(integrated).toContain('"-CudaRuntime", $CudaRuntime');
    expect(integrated).toContain('"-RuntimeVersionOverride", $runtimeVersion');
    expect(integrated).toContain('"-KeepExistingPackages"');

    expect(stageRuntime).toContain('[ValidateSet("cu128", "cu118")]');
    expect(stageRuntime).toContain("Get-CudaRuntimeMetadata");
    expect(stageRuntime).toContain("py311-cu128-v1");
    expect(stageRuntime).toContain("py311-cu118-v1");
    expect(stageRuntime).toContain("https://download.pytorch.org/whl/cu128");
    expect(stageRuntime).toContain("https://download.pytorch.org/whl/cu118");
    expect(stageRuntime).toContain("Update-RequirementsForCudaRuntime");
    expect(stageRuntime).toContain('Join-Path $cacheRoot (Join-Path "wheelhouse" $CudaRuntime)');
    expect(stageRuntime).toContain('Join-Path $cacheRoot (Join-Path "runtime-python" $CudaRuntime)');
    expect(stageRuntime).toContain('Join-Path $cacheRoot (Join-Path "staging-metadata" $CudaRuntime)');
    expect(stageRuntime).toContain("-UseHardLinks");

    expect(layered).toContain("$RuntimeVersionOverride");
    expect(layered).toContain("$KeepExistingPackages");
    expect(layered).toContain("$KeepExistingPackages -and (Test-Path -LiteralPath $archivePath)");
    expect(layered).toContain("Reusing existing package archive");
    expect(portable).toContain("$RuntimeVersionOverride");
    expect(packageJson).toContain("package:portable:cuda-variants");
    expect(packageJson).toContain("-BuildCudaRuntimeVariants");
  });

  it("auto-detects CUDA-suffixed portable roots for offline update acceptance", () => {
    const offlineUpdate = readFileSync(path.join(process.cwd(), "scripts", "test-portable-offline-update.ps1"), "utf-8");

    expect(offlineUpdate).toContain('-Filter "NeoTTS-Portable*"');
    expect(offlineUpdate).toContain('NeoTTS-Portable-cu128');
    expect(offlineUpdate).toContain('NeoTTS-Portable-cu118');
    expect(offlineUpdate).toContain('RuntimePriority');
    expect(offlineUpdate).toContain('Pass -BaselinePortableRoot');
  });
});
