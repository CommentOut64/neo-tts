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
  it("Phase 6: segmentTextDisplay 不再允许通过固定句号回推 stem", () => {
    const source = read("src/utils/segmentTextDisplay.ts");

    expect(source).not.toContain('rawText.endsWith("。")');
    expect(source).not.toContain("rawText.slice(0, -1)");
  });

  it("Phase 2: standardization preview 不再保留旧 display derive util", () => {
    expect(existsSync(resolve(rootDir, "src/utils/standardizationPreviewDisplay.ts"))).toBe(false);
  });

  it("Phase 6: editor 主路径不再保留 terminal capsule 旧软保护文件", () => {
    expect(
      existsSync(resolve(rootDir, "src/components/workspace/workspace-editor/terminalCapsuleProtection.ts")),
    ).toBe(false);
  });

  it("Phase 6: 前端正式段级事件类型不再暴露 raw_text 兼容字段", () => {
    const source = read("src/types/editSession.ts");

    expect(source).not.toContain("raw_text?: string");
  });
});
