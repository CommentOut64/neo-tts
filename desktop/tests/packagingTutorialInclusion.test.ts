import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

describe("packaging tutorial inclusion", () => {
  it("copies 使用教程.txt into the packaged app root before portable and installed assembly", () => {
    const filePath = path.join(process.cwd(), "scripts", "build-integrated-package.ps1");
    const source = readFileSync(filePath, "utf-8");

    expect(source).toContain('Join-Path $projectRoot "使用教程.txt"');
    expect(source).toContain('Join-Path $winUnpackedRoot "使用教程.txt"');
    expect(source).toContain('Copy-Item -LiteralPath $tutorialSourcePath -Destination $tutorialTargetPath -Force');
  });
});
