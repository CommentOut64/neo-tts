import { describe, expect, it } from "vitest";

import { formatVersionLabel } from "../src/composables/useAppUpdate";

describe("useAppUpdate", () => {
  it("adds a v prefix when the backend version is a plain semantic version", () => {
    expect(formatVersionLabel("0.0.1")).toBe("v0.0.1");
  });

  it("preserves an existing v prefix", () => {
    expect(formatVersionLabel("v0.0.1")).toBe("v0.0.1");
  });
});
