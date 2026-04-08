import { describe, expect, it } from "vitest";

import { extractWorkspaceEffectiveText } from "../src/utils/workspaceEffectiveText";

describe("workspaceEffectiveText", () => {
  it("会按文档顺序提取有效正文", () => {
    expect(
      extractWorkspaceEffectiveText({
        type: "doc",
        content: [
          { type: "paragraph", content: [{ type: "text", text: "第一段。" }] },
          { type: "paragraph", content: [{ type: "text", text: "第二段。" }] },
        ],
      }),
    ).toBe("第一段。第二段。");
  });

  it("空段落和嵌套 inline 节点不会打乱正文提取", () => {
    expect(
      extractWorkspaceEffectiveText({
        type: "doc",
        content: [
          { type: "paragraph", content: [] },
          {
            type: "paragraph",
            content: [
              { type: "text", text: "第一句" },
              {
                type: "span",
                content: [{ type: "text", text: "第二句" }],
              },
            ],
          },
        ],
      }),
    ).toBe("第一句第二句");
  });
});
