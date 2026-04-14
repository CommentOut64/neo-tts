import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

describe("electron-builder icon config", () => {
  it("declares a Windows app icon for packaged launchers", () => {
    const filePath = path.join(process.cwd(), "electron-builder.yml");
    const source = readFileSync(filePath, "utf-8");

    expect(source).toMatch(/win:\s*[\s\S]*icon:\s+/);
  });
});
