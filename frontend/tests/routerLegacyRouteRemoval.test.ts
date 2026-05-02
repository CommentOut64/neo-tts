import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

describe("legacy studio route removal", () => {
  it("does not register the /studio route anymore", () => {
    const filePath = path.join(process.cwd(), "src", "router", "index.ts");
    const source = readFileSync(filePath, "utf-8");

    expect(source).not.toContain("path: '/studio'");
    expect(source).not.toContain("name: 'TtsStudio'");
    expect(source).not.toContain("TtsStudioView.vue");
  });
});
