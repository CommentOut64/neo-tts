import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

function readSource(relativePath: string) {
  return readFileSync(new URL(relativePath, import.meta.url), "utf8");
}

describe("Nuxt UI color mode integration", () => {
  it("禁用 Nuxt UI 自带的 colorMode，避免刷新时覆盖自定义主题状态", () => {
    const source = readSource("../vite.config.ts");

    expect(source.includes("ui({ colorMode: false })")).toBe(true);
  });
});
