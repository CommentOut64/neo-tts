import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const exportDialogSource = readFileSync(
  resolve(
    dirname(fileURLToPath(import.meta.url)),
    "../src/components/workspace/ExportDialog.vue",
  ),
  "utf8",
);

describe("export dialog subtitle options", () => {
  it("ExportDialog exposes subtitle checkbox and offset input in order", () => {
    expect(exportDialogSource.indexOf("导出 SRT 字幕")).toBeGreaterThan(-1);
    expect(exportDialogSource.indexOf("全局偏移(秒)")).toBeGreaterThan(
      exportDialogSource.indexOf("导出 SRT 字幕"),
    );
  });

  it("disables offset selector until subtitle export is enabled", () => {
    expect(exportDialogSource).toContain(':disabled="isExporting || !includeSrt"');
  });

  it("removes legacy export naming helper copy from ExportDialog", () => {
    expect(exportDialogSource).not.toContain("整条导出会直接写入该目录");
    expect(exportDialogSource).not.toContain("分段导出会自动创建");
  });

  it("disables trailing punctuation toggle until subtitle export is enabled", () => {
    expect(exportDialogSource).toContain(':disabled="isExporting || !includeSrt"');
    expect(exportDialogSource).toContain("去除每段段末标点");
  });
});
