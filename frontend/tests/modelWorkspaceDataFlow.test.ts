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

describe("model workspace data flow", () => {
  it("workspace summary contract includes route metadata required by the model hub", () => {
    expect(ttsRegistryTypesSource).toContain("family_display_name");
    expect(ttsRegistryTypesSource).toContain("family_route_slug");
    expect(ttsRegistryTypesSource).toContain("binding_display_strategy");
  });

  it("model hub view wires workspace rows to the model workspace route", () => {
    expect(modelHubViewSource).toContain("useRouter");
    expect(modelHubViewSource).toContain("buildModelWorkspaceRouteLocation");
    expect(modelHubViewSource).toContain("@click=\"openWorkspace");
  });

  it("model workspace view resolves route params and loads the real workspace tree", () => {
    expect(modelWorkspaceViewSource).toContain("useRoute");
    expect(modelWorkspaceViewSource).toContain("fetchRegistryWorkspaces");
    expect(modelWorkspaceViewSource).toContain("fetchRegistryWorkspaceTree");
    expect(modelWorkspaceViewSource).toContain("findWorkspaceSummaryByRoute");
  });
});
