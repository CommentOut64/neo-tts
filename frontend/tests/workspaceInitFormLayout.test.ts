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
const workspaceViewSource = readFileSync(
  resolve(
    dirname(fileURLToPath(import.meta.url)),
    "../src/views/WorkspaceView.vue",
  ),
  "utf8",
);

describe("workspace init form layout", () => {
  it("Workspace 初始化表单会隐藏用户可调的切分策略", () => {
    expect(workspaceInitFormSource).toContain(':show-text-split-method="false"');
  });

  it("Workspace 初始化表单不会展示或缓存旧链路分段长度参数", () => {
    expect(workspaceInitFormSource).toContain(':show-chunk-length="false"');
    expect(workspaceInitFormSource).not.toContain("chunk_length: number");
    expect(workspaceViewSource).not.toContain("chunk_length: number");
    expect(workspaceViewSource).not.toContain("chunk_length: 24");
    expect(workspaceViewSource).not.toContain("chunk_length: syncedParams.chunk_length");
    expect(workspaceViewSource).not.toContain("nextParams.chunk_length = p.chunk_length");
  });

  it("切换音色时会从按 binding 的 reference 记忆恢复，而不是硬重置成全局 preset", () => {
    expect(workspaceInitFormSource).toContain("referenceSelectionsByBinding");
    expect(workspaceInitFormSource).toContain("resolveReferenceSelectionForBinding");
    expect(workspaceInitFormSource).toContain("handleReferenceSourceChange");
    expect(workspaceInitFormSource).toContain("resolveReferenceSelectionBySource");
  });

  it("Workspace 初始化缓存会写入按 binding 的 referenceSelectionsByBinding", () => {
    expect(workspaceViewSource).toContain("referenceSelectionsByBinding");
    expect(workspaceViewSource).not.toContain("voice: initParams.value.voice_id");
  });
});
