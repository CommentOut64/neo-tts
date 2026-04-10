import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
  resolveEndSessionChoiceResult,
  resolveEndSessionGuard,
} from "../src/components/workspace/sessionHandoff";

const endSessionDialogSource = readFileSync(
  resolve(
    dirname(fileURLToPath(import.meta.url)),
    "../src/components/workspace/EndSessionDialog.vue",
  ),
  "utf8",
);
const workspaceEditorHostSource = readFileSync(
  resolve(
    dirname(fileURLToPath(import.meta.url)),
    "../src/components/workspace/WorkspaceEditorHost.vue",
  ),
  "utf8",
);

describe("workspace end session flow", () => {
  it("没有待重推理内容时也必须先进入普通确认", () => {
    expect(
      resolveEndSessionGuard({
        hasPendingTextChanges: false,
        hasPendingRerender: false,
        hasDirtyParameterDraft: false,
        hasPendingReorderDraft: false,
      }),
    ).toBe("confirm_plain");
  });

  it("有文本待重推理内容时必须先进入三分支确认", () => {
    expect(
      resolveEndSessionGuard({
        hasPendingTextChanges: true,
        hasPendingRerender: true,
        hasDirtyParameterDraft: false,
        hasPendingReorderDraft: false,
      }),
    ).toBe("confirm_with_text_options");
  });

  it("只有参数相关待处理修改时应进入放弃或结束的确认", () => {
    expect(
      resolveEndSessionGuard({
        hasPendingTextChanges: false,
        hasPendingRerender: false,
        hasDirtyParameterDraft: true,
        hasPendingReorderDraft: false,
      }),
    ).toBe("confirm_discard_only");
    expect(
      resolveEndSessionGuard({
        hasPendingTextChanges: false,
        hasPendingRerender: true,
        hasDirtyParameterDraft: false,
        hasPendingReorderDraft: false,
      }),
    ).toBe("confirm_discard_only");
  });

  it("存在未应用重排时应进入应用或放弃的确认", () => {
    expect(
      resolveEndSessionGuard({
        hasPendingTextChanges: false,
        hasPendingRerender: false,
        hasDirtyParameterDraft: false,
        hasPendingReorderDraft: true,
      }),
    ).toBe("confirm_apply_reorder");
  });

  it("选择继续编辑时不会结束当前会话", () => {
    expect(
      resolveEndSessionChoiceResult({
        choice: "continue_editing",
        appliedText: "正式正文",
        workingText: "编辑中的正文",
      }),
    ).toEqual({
      shouldEndSession: false,
      nextInputText: null,
      nextInputSource: null,
      nextRoute: null,
    });
  });

  it("选择保留文字并结束会话时，会把 working_text 显式交接给输入页", () => {
    expect(
      resolveEndSessionChoiceResult({
        choice: "keep_working_text",
        appliedText: "正式正文",
        workingText: "编辑中的正文",
      }),
    ).toEqual({
      shouldEndSession: true,
      nextInputText: "编辑中的正文",
      nextInputSource: "input_handoff",
      nextRoute: "/workspace",
    });
  });

  it("选择撤销未重推理修改并结束会话时，会退回 applied_text", () => {
    expect(
      resolveEndSessionChoiceResult({
        choice: "discard_unapplied_changes",
        appliedText: "正式正文",
        workingText: "编辑中的正文",
      }),
    ).toEqual({
      shouldEndSession: true,
      nextInputText: "正式正文",
      nextInputSource: "applied_text",
      nextRoute: "/workspace",
    });
  });

  it("选择应用更新并结束会话时，会先触发结构更新再结束会话", () => {
    expect(
      resolveEndSessionChoiceResult({
        choice: "apply_updates_and_end_session",
        appliedText: "正式正文",
        workingText: "编辑中的正文",
      }),
    ).toEqual({
      shouldEndSession: true,
      shouldApplyUpdatesBeforeEndSession: true,
      nextInputText: "正式正文",
      nextInputSource: "applied_text",
      nextRoute: "/workspace",
    });
  });

  it("有文本待重推理内容时会使用更短的结束决策按钮文案", () => {
    expect(endSessionDialogSource).toContain("继续编辑");
    expect(endSessionDialogSource).toContain("放弃修改");
    expect(endSessionDialogSource).toContain('mode === "confirm_with_text_options" ? "保留文字" : "结束当前会话"');
    expect(endSessionDialogSource).not.toContain("撤销未重推理修改并结束会话");
    expect(endSessionDialogSource).not.toContain("保留文字并结束会话不会更新当前音频");
  });

  it("有文本待重推理内容时会用一句话说明结束后果与可选动作", () => {
    expect(endSessionDialogSource).toContain(
      "现在结束会话，这些修改不会进入当前音频。你可以继续编辑、保留文字并结束会话，或撤销这些修改后结束会话。",
    );
  });

  it("只有参数待处理时会提示这些修改不会进入当前音频，并且不再提供保留文字", () => {
    expect(endSessionDialogSource).toContain(
      "mode === 'confirm_discard_only'",
    );
    expect(endSessionDialogSource).toContain(
      "现在结束会话，这些修改不会进入当前音频。你可以继续编辑，或直接结束当前会话。",
    );
  });

  it("存在未应用重排时会明确提示可以应用顺序后结束", () => {
    expect(endSessionDialogSource).toContain("mode === 'confirm_apply_reorder'");
    expect(endSessionDialogSource).toContain(
      "当前有未应用的顺序调整。你可以继续编辑、应用调整后结束会话，或放弃调整后结束会话。",
    );
    expect(endSessionDialogSource).toContain("应用更新并结束");
  });

  it("无待重推理时会显示结束当前会话的普通确认文案", () => {
    expect(endSessionDialogSource).toContain("结束当前会话？");
    expect(endSessionDialogSource).toContain("结束当前会话后，将回到首次生成前。");
    expect(endSessionDialogSource).toContain("结束当前会话");
  });

  it("结束会话成功后会丢弃参数草稿，并由 editSession 统一收口", () => {
    expect(workspaceEditorHostSource).toContain("parameterPanel.discardDraft()");
    expect(workspaceEditorHostSource).toContain("await editSession.endSession(");
    expect(workspaceEditorHostSource).not.toContain("inputDraft.handoffFromWorkspace");
  });
});
