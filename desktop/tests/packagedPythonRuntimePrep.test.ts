import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

describe("packaged python runtime preparation", () => {
  it("extracts bundled nltk payload into runtime/python/nltk_data during stage-runtime", () => {
    const filePath = path.join(process.cwd(), "scripts", "stage-runtime.ps1");
    const source = readFileSync(filePath, "utf-8");

    expect(source).toContain('Join-Path $projectRoot "launcher\\internal\\nltkpatcher\\payload\\nltk_data"');
    expect(source).toContain('Join-Path $runtimePythonDir "nltk_data"');
    expect(source).toContain('"nltk-payload-layout-v2"');
    expect(source).toContain("cmudict.zip");
    expect(source).toContain("averaged_perceptron_tagger.zip");
    expect(source).toContain("averaged_perceptron_tagger_eng.zip");
    expect(source).toContain('$runtimeNltkCorporaZipPath = Join-Path $runtimeNltkCorporaDir "cmudict.zip"');
    expect(source).toContain(
      '$runtimeNltkAveragedPerceptronTaggerZipPath = Join-Path $runtimeNltkTaggersDir "averaged_perceptron_tagger.zip"',
    );
    expect(source).toContain(
      '$runtimeNltkAveragedPerceptronTaggerEngZipPath = Join-Path $runtimeNltkTaggersDir "averaged_perceptron_tagger_eng.zip"',
    );
    expect(source).toContain("Copy-Item -LiteralPath $cmudictPayloadPath -Destination $runtimeNltkCorporaZipPath -Force");
    expect(source).toContain(
      "Copy-Item -LiteralPath $averagedPerceptronTaggerPayloadPath -Destination $runtimeNltkAveragedPerceptronTaggerZipPath -Force",
    );
    expect(source).toContain(
      "Copy-Item -LiteralPath $averagedPerceptronTaggerEngPayloadPath -Destination $runtimeNltkAveragedPerceptronTaggerEngZipPath -Force",
    );
  });

  it("does not run packaged python compileall during final artifact assembly", () => {
    const filePath = path.join(process.cwd(), "scripts", "build-integrated-package.ps1");
    const source = readFileSync(filePath, "utf-8");

    expect(source).not.toContain("Invoke-PackagedPythonCompile");
    expect(source).not.toContain('Invoke-NativeStep -Label "Compile packaged Python runtime"');
    expect(source).not.toContain('"compileall"');

    const builderIndex = source.indexOf('Invoke-NativeStep -Label "Build Windows dir artifact"');
    const assembleIndex = source.indexOf('Invoke-NativeStep -Label $portableLabel');
    const installerIndex = source.indexOf('Invoke-NativeStep -Label "Build Windows installer with Inno Setup"');

    expect(builderIndex).toBeGreaterThan(-1);
    expect(assembleIndex).toBeGreaterThan(builderIndex);
    expect(installerIndex).toBeGreaterThan(builderIndex);
  });
});
