import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

function resolveFromTests(relativePath: string) {
  return resolve(dirname(fileURLToPath(import.meta.url)), relativePath);
}

const modelHubViewSource = readFileSync(resolveFromTests("../src/views/ModelHubView.vue"), "utf8");
const modelWorkspaceViewSource = readFileSync(resolveFromTests("../src/views/ModelWorkspaceView.vue"), "utf8");
const ttsRegistryTypesSource = readFileSync(resolveFromTests("../src/types/ttsRegistry.ts"), "utf8");
const modelWorkspaceAdminSource = readFileSync(
  resolveFromTests("../src/composables/useModelWorkspaceAdmin.ts"),
  "utf8",
);

describe("model workspace data flow", () => {
  it("workspace summary contract includes route metadata required by the model hub", () => {
    expect(ttsRegistryTypesSource).toContain("family_display_name");
    expect(ttsRegistryTypesSource).toContain("family_route_slug");
    expect(ttsRegistryTypesSource).toContain("binding_display_strategy");
  });

  it("model hub view still wires workspace rows to the model workspace route", () => {
    expect(modelHubViewSource).toContain("useRouter");
    expect(modelHubViewSource).toContain("buildModelWorkspaceRouteLocation");
    expect(modelHubViewSource).toContain("openEditWorkspaceDialog");
    expect(modelHubViewSource).toContain("openDeleteWorkspaceDialog");
  });

  it("workspace admin composable owns the route context, tree loading and selection state", () => {
    expect(modelWorkspaceAdminSource).toContain("workspaceSummary");
    expect(modelWorkspaceAdminSource).toContain("workspaceTree");
    expect(modelWorkspaceAdminSource).toContain("familyDefinition");
    expect(modelWorkspaceAdminSource).toContain("selectedMainModelId");
    expect(modelWorkspaceAdminSource).toContain("selectedSubmodelId");
    expect(modelWorkspaceAdminSource).toContain("loadWorkspaceRouteContext");
    expect(modelWorkspaceAdminSource).toContain("loadWorkspaceTree");
    expect(modelWorkspaceAdminSource).toContain("loadFamilyDefinition");
    expect(modelWorkspaceAdminSource).toContain("restoreWorkspaceSelection");
  });

  it("model workspace view delegates runtime state and list selection to the admin composable", () => {
    expect(modelWorkspaceViewSource).toContain("useModelWorkspaceAdmin");
    expect(modelWorkspaceViewSource).toContain("ModelWorkspaceHeader");
    expect(modelWorkspaceViewSource).toContain("MainModelListPanel");
    expect(modelWorkspaceViewSource).toContain("SubmodelListPanel");
    expect(modelWorkspaceViewSource).toContain("PresetListPanel");
  });
});
