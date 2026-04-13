import { describe, expect, it } from "vitest";

import {
  protectTerminalCapsule,
  sanitizeWorkspaceViewDocTerminalCapsules,
} from "../src/components/workspace/workspace-editor/terminalCapsuleProtection";

describe("workspace terminal capsule protection", () => {
  it("正文和句尾一起被替换时，只改正文并恢复原 capsule", () => {
    expect(
      protectTerminalCapsule({
        previousText: "今天下雨了。",
        nextText: "今天先暂停一下……",
      }),
    ).toEqual({
      text: "今天先暂停一下。",
      touchedCapsule: true,
      changedText: true,
    });
  });

  it("只命中句尾时，不产生正文修改", () => {
    expect(
      protectTerminalCapsule({
        previousText: "今天下雨了。",
        nextText: "今天下雨了X",
      }),
    ).toEqual({
      text: "今天下雨了。",
      touchedCapsule: true,
      changedText: false,
    });
  });

  it("保留原始句尾簇和尾随闭合符", () => {
    expect(
      protectTerminalCapsule({
        previousText: "真的吗？！」",
        nextText: "真的要继续……",
      }),
    ).toEqual({
      text: "真的要继续？！」",
      touchedCapsule: true,
      changedText: true,
    });
  });

  it("没有命中句尾时保持正常正文修改", () => {
    expect(
      protectTerminalCapsule({
        previousText: "第一句。",
        nextText: "新的第一句。",
      }),
    ).toEqual({
      text: "新的第一句。",
      touchedCapsule: false,
      changedText: true,
    });
  });

  it("没有句尾的段不做保护", () => {
    expect(
      protectTerminalCapsule({
        previousText: "没有句号",
        nextText: "还是没有句号",
      }),
    ).toEqual({
      text: "还是没有句号",
      touchedCapsule: false,
      changedText: true,
    });
  });

  it("能修正列表式视图里被改坏的句尾胶囊", () => {
    expect(
      sanitizeWorkspaceViewDocTerminalCapsules({
        previousDoc: {
          type: "doc",
          content: [
            {
              type: "segmentBlock",
              attrs: { segmentId: "seg-1" },
              content: [{ type: "text", text: "今天下雨了。" }],
            },
          ],
        },
        nextDoc: {
          type: "doc",
          content: [
            {
              type: "segmentBlock",
              attrs: { segmentId: "seg-1" },
              content: [{ type: "text", text: "今天先暂停一下……" }],
            },
          ],
        },
        orderedSegmentIds: ["seg-1"],
      }),
    ).toEqual({
      doc: {
        type: "doc",
        content: [
          {
            type: "segmentBlock",
            attrs: { segmentId: "seg-1" },
            content: [{ type: "text", text: "今天先暂停一下。" }],
          },
        ],
      },
      touchedCapsule: true,
      changedText: true,
    });
  });

  it("能修正组合式视图里被改坏的句尾胶囊", () => {
    expect(
      sanitizeWorkspaceViewDocTerminalCapsules({
        previousDoc: {
          type: "doc",
          content: [
            {
              type: "paragraph",
              content: [
                {
                  type: "text",
                  text: "真的吗？！」",
                  marks: [{ type: "segmentAnchor", attrs: { segmentId: "seg-1" } }],
                },
              ],
            },
          ],
        },
        nextDoc: {
          type: "doc",
          content: [
            {
              type: "paragraph",
              content: [
                {
                  type: "text",
                  text: "真的要继续……",
                  marks: [{ type: "segmentAnchor", attrs: { segmentId: "seg-1" } }],
                },
              ],
            },
          ],
        },
        orderedSegmentIds: ["seg-1"],
      }),
    ).toEqual({
      doc: {
        type: "doc",
        content: [
          {
            type: "paragraph",
            content: [
              {
                type: "text",
                text: "真的要继续？！」",
                marks: [{ type: "segmentAnchor", attrs: { segmentId: "seg-1" } }],
              },
            ],
          },
        ],
      },
      touchedCapsule: true,
      changedText: true,
    });
  });
});
