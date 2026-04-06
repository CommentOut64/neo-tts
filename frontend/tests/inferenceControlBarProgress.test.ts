import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

describe("InferenceControlBar progress animation", () => {
  it("uses eased width transition for the inference progress bar", () => {
    const source = readFileSync(
      new URL("../src/components/InferenceControlBar.vue", import.meta.url),
      "utf8",
    );

    expect(source.includes("class=\"inference-progress mb-1\"")).toBe(true);
    expect(source.includes("transition: width 0.45s cubic-bezier(")).toBe(true);
  });
});
