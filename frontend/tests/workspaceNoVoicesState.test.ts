import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

describe("Workspace no voices state", () => {
  it("在 binding catalog 为空时展示待配置状态，并引导到 /models", () => {
    const filePath = path.join(process.cwd(), "src", "views", "WorkspaceView.vue");
    const source = readFileSync(filePath, "utf-8");

    expect(source).toContain("当前还没有可用模型");
    expect(source).toContain("/models");
    expect(source).toContain("前往模型管理");
    expect(source).not.toContain("/v1/voices");
  });
});
