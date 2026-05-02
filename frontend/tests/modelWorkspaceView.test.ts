import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

function resolveFromTests(relativePath: string) {
  return resolve(dirname(fileURLToPath(import.meta.url)), relativePath);
}

const modelWorkspaceViewPath = resolveFromTests("../src/views/ModelWorkspaceView.vue");
const workspaceDialogPath = resolveFromTests("../src/components/model-center/WorkspaceDialog.vue");
const mainModelDialogPath = resolveFromTests("../src/components/model-center/MainModelDialog.vue");
const submodelDialogPath = resolveFromTests("../src/components/model-center/SubmodelDialog.vue");
const presetDialogPath = resolveFromTests("../src/components/model-center/PresetDialog.vue");
const secretEditorDialogPath = resolveFromTests("../src/components/model-center/SecretEditorDialog.vue");
const deleteConfirmDialogPath = resolveFromTests("../src/components/model-center/DeleteConfirmDialog.vue");
const workspaceHeaderPath = resolveFromTests("../src/components/model-center/ModelWorkspaceHeader.vue");
const mainModelListPanelPath = resolveFromTests("../src/components/model-center/MainModelListPanel.vue");
const submodelListPanelPath = resolveFromTests("../src/components/model-center/SubmodelListPanel.vue");
const presetListPanelPath = resolveFromTests("../src/components/model-center/PresetListPanel.vue");
const routerPath = resolveFromTests("../src/router/index.ts");
const routerSource = readFileSync(routerPath, "utf8");

describe("model workspace view", () => {
  it("registers the family workspace route under /models/:familyRoute/:workspaceSlug", () => {
    expect(routerSource).toContain("path: '/models/:familyRoute/:workspaceSlug'");
    expect(routerSource).toContain("ModelWorkspaceView.vue");
  });

  it("family workspace view exists and is backed by dedicated model-center components", () => {
    expect(existsSync(modelWorkspaceViewPath)).toBe(true);
    expect(existsSync(workspaceDialogPath)).toBe(true);
  });

  it("family workspace view is no longer a static schema placeholder", () => {
    const modelWorkspaceViewSource = readFileSync(modelWorkspaceViewPath, "utf8");
    expect(modelWorkspaceViewSource).toContain("useModelWorkspaceAdmin");
    expect(modelWorkspaceViewSource).toContain("selectedMainModel");
    expect(modelWorkspaceViewSource).toContain("selectedPresets");
  });

  it("dialog skeletons exist and keep secret editing separate from normal schema forms", () => {
    expect(existsSync(workspaceDialogPath)).toBe(true);
    expect(existsSync(mainModelDialogPath)).toBe(true);
    expect(existsSync(submodelDialogPath)).toBe(true);
    expect(existsSync(presetDialogPath)).toBe(true);
    expect(existsSync(secretEditorDialogPath)).toBe(true);
    expect(existsSync(deleteConfirmDialogPath)).toBe(true);

    expect(readFileSync(workspaceDialogPath, "utf8")).toContain("ModelSchemaForm");
    expect(readFileSync(mainModelDialogPath, "utf8")).toContain("ModelSchemaForm");
    expect(readFileSync(submodelDialogPath, "utf8")).toContain("ModelSchemaForm");
    expect(readFileSync(presetDialogPath, "utf8")).toContain("ModelSchemaForm");
    expect(readFileSync(secretEditorDialogPath, "utf8")).not.toContain("ModelSchemaForm");
    expect(readFileSync(deleteConfirmDialogPath, "utf8")).toContain("submit");
  });

  it("workspace view is wired to the admin composable and list panels instead of schema placeholders", () => {
    expect(existsSync(workspaceHeaderPath)).toBe(true);
    expect(existsSync(mainModelListPanelPath)).toBe(true);
    expect(existsSync(submodelListPanelPath)).toBe(true);
    expect(existsSync(presetListPanelPath)).toBe(true);

    const modelWorkspaceViewSource = readFileSync(modelWorkspaceViewPath, "utf8");
    expect(modelWorkspaceViewSource).toContain("useModelWorkspaceAdmin");
    expect(modelWorkspaceViewSource).toContain("ModelWorkspaceHeader");
    expect(modelWorkspaceViewSource).toContain("MainModelListPanel");
    expect(modelWorkspaceViewSource).toContain("SubmodelListPanel");
    expect(modelWorkspaceViewSource).toContain("PresetListPanel");
    expect(modelWorkspaceViewSource).not.toContain("ModelSchemaForm");
    expect(modelWorkspaceViewSource).not.toContain("workspaceSchema");
  });

  it("workspace header and view expose a dedicated GPT-SoVITS package import entry", () => {
    const modelWorkspaceViewSource = readFileSync(modelWorkspaceViewPath, "utf8");
    const workspaceHeaderSource = readFileSync(workspaceHeaderPath, "utf8");

    expect(modelWorkspaceViewSource).toContain("openImportModelPackageDialog");
    expect(modelWorkspaceViewSource).toContain("@import-model-package");
    expect(workspaceHeaderSource).toContain("importModelPackage");
  });
});
