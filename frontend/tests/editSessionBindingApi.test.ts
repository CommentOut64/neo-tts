import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

function resolveFromTests(relativePath: string) {
  return resolve(dirname(fileURLToPath(import.meta.url)), relativePath);
}

const editSessionApiSource = readFileSync(resolveFromTests("../src/api/editSession.ts"), "utf8");
const editSessionTypesSource = readFileSync(resolveFromTests("../src/types/editSession.ts"), "utf8");

describe("edit session synthesis binding protocol", () => {
  it("uses synthesis-binding routes instead of voice-binding routes", () => {
    expect(editSessionApiSource).toContain("/v1/edit-session/session/synthesis-binding");
    expect(editSessionApiSource).toContain("/v1/edit-session/segments/${segmentId}/synthesis-binding");
    expect(editSessionApiSource).not.toContain("/v1/edit-session/session/voice-binding");
    expect(editSessionApiSource).not.toContain("/v1/edit-session/segments/${segmentId}/voice-binding");
  });

  it("frontend formal types expose synthesis binding names instead of voice binding names", () => {
    expect(editSessionTypesSource).toContain("export interface SynthesisBinding");
    expect(editSessionTypesSource).toContain("export interface SynthesisBindingPatch");
    expect(editSessionTypesSource).not.toContain("export interface VoiceBinding");
    expect(editSessionTypesSource).not.toContain("export interface VoiceBindingPatch");
  });
});
