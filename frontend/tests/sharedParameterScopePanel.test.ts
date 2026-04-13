import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

function resolveFromTests(relativePath: string) {
  return resolve(dirname(fileURLToPath(import.meta.url)), relativePath);
}

const sharedParameterScopePanelSource = readFileSync(
  resolveFromTests("../src/components/workspace/parameter-panel/SharedParameterScopePanel.vue"),
  "utf8",
);

describe("shared parameter scope panel", () => {
  it("切换目标音色时不应把 model_key 写成 voiceId", () => {
    expect(sharedParameterScopePanelSource).not.toContain(
      'panel.updateVoiceBindingField("model_key", voiceId);',
    );
    expect(sharedParameterScopePanelSource).toContain(
      "DEFAULT_REFERENCE_BINDING_MODEL_KEY",
    );
  });
});
