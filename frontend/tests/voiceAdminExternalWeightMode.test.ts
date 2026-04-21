import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

describe("VoiceAdmin external weight mode", () => {
  it("外部权重模式使用 FileUploader 路径选择，而不是手填绝对路径输入框", () => {
    const filePath = path.join(process.cwd(), "src", "views", "VoiceAdminView.vue");
    const source = readFileSync(filePath, "utf-8");

    expect(source).toContain('selectionMode="path"');
    expect(source).not.toContain("GPT 外部绝对路径");
    expect(source).not.toContain("SoVITS 外部绝对路径");
  });
});
