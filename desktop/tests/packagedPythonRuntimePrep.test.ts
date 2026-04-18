import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

describe("packaged python runtime preparation", () => {
  it("extracts bundled nltk payload into runtime/python/nltk_data during stage-runtime", () => {
    const filePath = path.join(process.cwd(), "scripts", "stage-runtime.ps1");
    const source = readFileSync(filePath, "utf-8");

    expect(source).toContain('Join-Path $projectRoot "launcher\\internal\\nltkpatcher\\payload\\nltk_data"');
    expect(source).toContain('Join-Path $runtimePythonDir "nltk_data"');
    expect(source).toContain("cmudict.zip");
    expect(source).toContain("averaged_perceptron_tagger.zip");
    expect(source).toContain("averaged_perceptron_tagger_eng.zip");
  });

  it("compiles packaged python after builder and before final artifact assembly", () => {
    const filePath = path.join(process.cwd(), "scripts", "build-integrated-package.ps1");
    const source = readFileSync(filePath, "utf-8");

    expect(source).toContain('Invoke-NativeStep -Label "Compile packaged Python runtime"');
    expect(source).toContain('"compileall"');
    expect(source).toContain('Join-Path $winUnpackedRoot "resources\\app-runtime\\backend"');
    expect(source).toContain('Join-Path $winUnpackedRoot "resources\\app-runtime\\GPT_SoVITS"');
    expect(source).toContain('Join-Path $winUnpackedRoot "resources\\app-runtime\\runtime\\python\\Lib\\site-packages"');

    const builderIndex = source.indexOf('Invoke-NativeStep -Label "Build Windows dir artifact"');
    const compileIndex = source.indexOf(
      "Invoke-PackagedPythonCompile -WinUnpackedRoot $winUnpackedRoot -WorkingDirectory $desktopRoot",
    );
    const assembleIndex = source.indexOf('Invoke-NativeStep -Label $portableLabel');
    const installerIndex = source.indexOf('Invoke-NativeStep -Label "Build Windows installer with Inno Setup"');

    expect(builderIndex).toBeGreaterThan(-1);
    expect(compileIndex).toBeGreaterThan(builderIndex);
    expect(assembleIndex).toBeGreaterThan(compileIndex);
    expect(installerIndex).toBeGreaterThan(compileIndex);
  });
});
