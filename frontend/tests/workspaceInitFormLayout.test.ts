import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const workspaceInitFormSource = readFileSync(
  resolve(
    dirname(fileURLToPath(import.meta.url)),
    "../src/components/workspace/WorkspaceInitForm.vue",
  ),
  "utf8",
);

describe("workspace init form layout", () => {
  it("Workspace 初始化表单会隐藏用户可调的切分策略", () => {
    expect(workspaceInitFormSource).toContain(':show-text-split-method="false"');
  });
});
