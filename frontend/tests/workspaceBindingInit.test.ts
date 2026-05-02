import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

function resolveFromTests(relativePath: string) {
  return resolve(dirname(fileURLToPath(import.meta.url)), relativePath);
}

const editSessionContractPath = resolveFromTests("../src/api/editSessionContract.ts");
const editSessionTypesPath = resolveFromTests("../src/types/editSession.ts");
const ttsRegistryApiPath = resolveFromTests("../src/api/ttsRegistry.ts");
const workspaceInitFormPath = resolveFromTests("../src/components/workspace/WorkspaceInitForm.vue");

const editSessionContractSource = readFileSync(editSessionContractPath, "utf8");
const editSessionTypesSource = readFileSync(editSessionTypesPath, "utf8");
const ttsRegistryApiSource = readFileSync(ttsRegistryApiPath, "utf8");
const workspaceInitFormSource = readFileSync(workspaceInitFormPath, "utf8");

describe("workspace binding init", () => {
  it("initialize request contract switches from voice_id to binding_ref", () => {
    expect(editSessionTypesSource).toContain("binding_ref");
    expect(editSessionTypesSource).not.toContain("voice_id: string");
    expect(editSessionContractSource).toContain("binding_ref");
    expect(editSessionContractSource).not.toContain("voice_id: draft.voiceId");
  });

  it("workspace init reads binding catalog from tts registry instead of voices", () => {
    expect(ttsRegistryApiSource).toContain("/v1/tts-registry/bindings/catalog");
    expect(ttsRegistryApiSource).toContain("fetchBindingCatalog");
    expect(workspaceInitFormSource).toContain("binding");
    expect(workspaceInitFormSource).not.toContain("VoiceSelect");
  });
});
