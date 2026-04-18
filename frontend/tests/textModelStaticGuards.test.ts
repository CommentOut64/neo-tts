import { readFileSync } from "node:fs";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const rootDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function read(relativePath: string): string {
  return readFileSync(resolve(rootDir, relativePath), "utf8");
}

describe("text model static guards", () => {
  it("Phase 0 baseline: segmentTextDisplay 仍包含固定句号 stem 回推", () => {
    const source = read("src/utils/segmentTextDisplay.ts");

    expect(source).toContain('rawText.endsWith("。")');
    expect(source).toContain("rawText.slice(0, -1)");
  });

  it("Phase 2: standardization preview 不再保留旧 display derive util", () => {
    expect(existsSync(resolve(rootDir, "src/utils/standardizationPreviewDisplay.ts"))).toBe(false);
  });
});
