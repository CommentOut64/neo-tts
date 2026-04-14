import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

describe("AboutDialog", () => {
  it("uses an explicit external-link handler so GitHub and Bilibili open outside Electron", () => {
    const filePath = path.join(process.cwd(), "src", "components", "AboutDialog.vue");
    const source = readFileSync(filePath, "utf-8");

    expect(source).toContain("@click.prevent=\"handleOpenExternal('https://github.com/CommentOut64/neo-tts')\"");
    expect(source).toContain("@click.prevent=\"handleOpenExternal('https://space.bilibili.com/515407408')\"");
  });

  it("renders the about version label with a v-prefixed display value", () => {
    const filePath = path.join(process.cwd(), "src", "components", "AboutDialog.vue");
    const source = readFileSync(filePath, "utf-8");

    expect(source).toContain("版本 {{ displayVersion }}");
  });
});
