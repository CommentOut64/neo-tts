import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

describe("RenderJobProgressBar animation", () => {
  it("uses eased width transition for render job progress bar", () => {
    const source = readFileSync(
      new URL("../src/components/workspace/RenderJobProgressBar.vue", import.meta.url),
      "utf8",
    );

    expect(source.includes("class=\"render-job-progress\"")).toBe(true);
    expect(source.includes("transition: width 0.45s cubic-bezier(")).toBe(true);
  });
});
