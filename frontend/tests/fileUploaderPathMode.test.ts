import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

describe("FileUploader path mode", () => {
  it("非 electron 的路径模式点击会走后端文件选择窗，拖拽会提示改用点击选择", () => {
    const filePath = path.join(process.cwd(), "src", "components", "FileUploader.vue");
    const source = readFileSync(filePath, "utf-8");

    expect(source).toContain("selectAbsolutePathForFile");
    expect(source).toContain("当前运行环境不支持通过拖拽解析绝对路径，请点击选择文件");
  });
});
