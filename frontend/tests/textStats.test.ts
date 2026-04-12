import { describe, expect, it } from "vitest";

import { countNonPunctuationCharacters } from "../src/utils/textStats";

describe("textStats", () => {
  it("统计时会排除中英文标点与空白", () => {
    expect(countNonPunctuationCharacters("Hello，世界！\n")).toBe(7);
  });
});
