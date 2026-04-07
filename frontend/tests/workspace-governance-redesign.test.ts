import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

function readSource(relativePath: string) {
  return readFileSync(new URL(relativePath, import.meta.url), "utf8");
}

describe("workspace governance redesign", () => {
  it("WorkspaceView 不再渲染会话操作 card，也不再接 baseline/reset dialog", () => {
    const source = readSource("../src/views/WorkspaceView.vue");

    expect(source.includes("会话操作")).toBe(false);
    expect(source.includes("BaselineRestoreDialog")).toBe(false);
    expect(source.includes("ResetSessionDialog")).toBe(false);
    expect(source.includes("<ExportDialog")).toBe(true);
  });

  it("WorkspaceEditorHost 保留正文区次级按钮与本地清空确认弹窗", () => {
    const source = readSource("../src/components/workspace/WorkspaceEditorHost.vue");

    expect(source.includes("转到文本输入页继续编辑")).toBe(true);
    expect(source.includes("清空会话")).toBe(true);
    expect(source.includes("ResetSessionDialog")).toBe(true);
  });

  it("AppNavbar 恢复旧版导航样式后，再最小化加入导出按钮并保留旧 placeholder", () => {
    const source = readSource("../src/components/AppNavbar.vue");

    expect(source.includes("bg-accent rounded-full")).toBe(true);
    expect(source.includes("导出")).toBe(true);
    expect(source.includes("runtime-state-placeholder")).toBe(true);
    expect(source.includes("export-action-placeholder")).toBe(true);
    expect(source.includes("closeExportDialog()")).toBe(true);
  });

  it("ExportDialog 改为导出窗口，并且只依赖持久化 document_version", () => {
    const source = readSource("../src/components/workspace/ExportDialog.vue");

    expect(source.includes("width=\"920px\"")).toBe(true);
    expect(source.includes("destroy-on-close")).toBe(true);
    expect(source.includes("snapshot.value?.document_version")).toBe(true);
    expect(source.includes("isExportBlockedByRenderJob")).toBe(true);
  });

  it("离开 workspace 或重新进入前，会主动收口残留的导出弹窗状态", () => {
    const navbarSource = readSource("../src/components/AppNavbar.vue");
    const workspaceSource = readSource("../src/views/WorkspaceView.vue");
    const dialogStateSource = readSource("../src/composables/useWorkspaceDialogState.ts");

    expect(dialogStateSource.includes("function closeExportDialog()")).toBe(true);
    expect(navbarSource.includes("if (path !== '/workspace')")).toBe(true);
    expect(workspaceSource.includes("onBeforeUnmount(() => {")).toBe(true);
    expect(workspaceSource.includes("dialogState.closeExportDialog()")).toBe(true);
  });
});
