import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

describe("UpdateDialog", () => {
  it("renders layered package list and restart action instead of a raw external download link", () => {
    const filePath = path.join(process.cwd(), "src", "components", "UpdateDialog.vue");
    const source = readFileSync(filePath, "utf-8");

    expect(source).toContain("changedPackages");
    expect(source).toContain("立即下载");
    expect(source).toContain("立即重启并更新");
    expect(source).not.toContain("window.open(props.updateInfo.download_url");
  });

  it("shows layered progress and rollback guidance instead of a generic placeholder summary", () => {
    const filePath = path.join(process.cwd(), "src", "components", "UpdateDialog.vue");
    const source = readFileSync(filePath, "utf-8");

    expect(source).toContain("completedPackages");
    expect(source).toContain("currentPackageId");
    expect(source).toContain("已回滚到当前稳定版本");
    expect(source).toContain("查看发布说明");
  });
});
