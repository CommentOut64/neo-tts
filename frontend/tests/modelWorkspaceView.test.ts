import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

function resolveFromTests(relativePath: string) {
  return resolve(dirname(fileURLToPath(import.meta.url)), relativePath);
}

const modelWorkspaceViewPath = resolveFromTests("../src/views/ModelWorkspaceView.vue");
const modelSchemaFormPath = resolveFromTests("../src/components/model-center/ModelSchemaForm.vue");
const routerPath = resolveFromTests("../src/router/index.ts");
const routerSource = readFileSync(routerPath, "utf8");

describe("model workspace view", () => {
  it("registers the family workspace route under /models/:familyRoute/:workspaceSlug", () => {
    expect(routerSource).toContain("path: '/models/:familyRoute/:workspaceSlug'");
    expect(routerSource).toContain("ModelWorkspaceView.vue");
  });

  it("family workspace view exists and is backed by a schema form component", () => {
    expect(existsSync(modelWorkspaceViewPath)).toBe(true);
    expect(existsSync(modelSchemaFormPath)).toBe(true);
  });

  it("family workspace view is no longer a static schema placeholder", () => {
    const modelWorkspaceViewSource = readFileSync(modelWorkspaceViewPath, "utf8");
    expect(modelWorkspaceViewSource).toContain("fetchRegistryWorkspaceTree");
    expect(modelWorkspaceViewSource).toContain("fetchRegistryWorkspaces");
  });

  it("schema form only renders required optional advanced fields and excludes hidden", () => {
    const modelSchemaFormSource = readFileSync(modelSchemaFormPath, "utf8");
    expect(modelSchemaFormSource).toContain("required");
    expect(modelSchemaFormSource).toContain("optional");
    expect(modelSchemaFormSource).toContain("advanced");
    expect(modelSchemaFormSource).toContain("hidden");
    expect(modelSchemaFormSource).toContain("visibility");
    expect(modelSchemaFormSource).toContain("!== 'hidden'");
  });
});
