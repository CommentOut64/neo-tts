import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

describe("FileUploader ref state", () => {
  it("selectedEntry 必须是可空 Ref，而不是错误的泛型断开写法", () => {
    const filePath = path.join(process.cwd(), "src", "components", "FileUploader.vue");
    const source = readFileSync(filePath, "utf-8");

    expect(source).toContain("const selectedEntry = ref<{");
    expect(source).toContain("detail: string");
    expect(source).toContain("} | null>(null)");
    expect(source).not.toContain("}> | null>(null)");
  });
});
