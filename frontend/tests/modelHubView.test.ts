import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

function resolveFromTests(relativePath: string) {
  return resolve(dirname(fileURLToPath(import.meta.url)), relativePath);
}

const routerPath = resolveFromTests("../src/router/index.ts");
const routerSource = readFileSync(routerPath, "utf8");
const modelHubViewPath = resolveFromTests("../src/views/ModelHubView.vue");
const ttsRegistryApiPath = resolveFromTests("../src/api/ttsRegistry.ts");
const ttsRegistryApiSource = readFileSync(ttsRegistryApiPath, "utf8");

describe("model hub view", () => {
  it("router registers /models and removes the formal /voices business route", () => {
    expect(routerSource).toContain("path: '/models'");
    expect(routerSource).not.toContain("path: '/voices'");
    expect(routerSource).toContain("ModelHubView.vue");
  });

  it("model hub view exists and reads workspace summaries from the registry", () => {
    expect(existsSync(modelHubViewPath)).toBe(true);
    const modelHubViewSource = readFileSync(modelHubViewPath, "utf8");
    expect(modelHubViewSource).toContain("/v1/tts-registry/workspaces");
    expect(modelHubViewSource).toContain("/v1/tts-registry/adapters");
  });

  it("tts registry api exposes workspace catalog helpers for the model hub", () => {
    expect(ttsRegistryApiSource).toContain("fetchRegistryWorkspaces");
    expect(ttsRegistryApiSource).toContain("createRegistryWorkspace");
  });
});
