import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

describe("AppNavbar icon asset", () => {
  it("does not hardcode the project icon to an absolute root path", () => {
    const filePath = path.join(process.cwd(), "src", "components", "AppNavbar.vue");
    const source = readFileSync(filePath, "utf-8");

    expect(source).not.toContain("url('/carbon--ibm-watson-text-to-speech.svg')");
    expect(source).not.toContain("-webkit-mask: url('/carbon--ibm-watson-text-to-speech.svg')");
  });

  it("renders the project icon without relying on CSS mask support", () => {
    const filePath = path.join(process.cwd(), "src", "components", "AppNavbar.vue");
    const source = readFileSync(filePath, "utf-8");

    expect(source).not.toContain("projectIconMaskStyle");
    expect(source).not.toContain("mask: url(");
    expect(source).not.toContain("-webkit-mask:");
  });
});
