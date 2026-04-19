import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

describe("AppNavbar actions", () => {
  it("hides the top-level exit button from the navbar", () => {
    const filePath = path.join(process.cwd(), "src", "components", "AppNavbar.vue");
    const source = readFileSync(filePath, "utf-8");

    expect(source).not.toContain("useAppExit");
    expect(source).not.toContain("@click=\"requestExit\"");
    expect(source).not.toContain(">退出<");
  });
});
