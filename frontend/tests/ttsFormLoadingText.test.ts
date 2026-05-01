import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

describe("inference loading text", () => {
  it("会把首次推理等待提醒放在 workspace 加载文案，而不是其他组件文案", () => {
    const renderJobControlsPath = path.join(
      process.cwd(),
      "src",
      "components",
      "workspace",
      "renderJobControls.ts",
    );
    const renderJobControlsSource = readFileSync(renderJobControlsPath, "utf-8");

    expect(renderJobControlsSource).toContain("首次推理耗时可能较长，请耐心等待");
  });
});
