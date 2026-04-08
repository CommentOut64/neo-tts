import { describe, expect, it } from "vitest";

import {
  getPrimaryRenderActionKind,
  getPrimaryRenderActionLabel,
  resolveWorkspaceProgressState,
} from "../src/components/workspace/renderJobControls";

describe("render job controls", () => {
  it("paused 状态主按钮应切换为恢复", () => {
    expect(getPrimaryRenderActionKind("paused")).toBe("resume");
    expect(getPrimaryRenderActionLabel("paused")).toBe("恢复");
  });

  it("非 paused 状态主按钮保持暂停", () => {
    expect(getPrimaryRenderActionKind("rendering")).toBe("pause");
    expect(getPrimaryRenderActionLabel("rendering")).toBe("暂停");
  });

  it("有活动 TTS 推理时优先显示 TTS 进度", () => {
    const resolved = resolveWorkspaceProgressState({
      inferenceProgress: {
        task_id: "tts-1",
        status: "inferencing",
        progress: 0.64,
        message: "第 3/5 段处理完成。",
        cancel_requested: false,
        current_segment: 3,
        total_segments: 5,
        result_id: null,
        updated_at: "2026-04-06T00:00:00.000Z",
      },
      renderJob: {
        job_id: "job-1",
        document_id: "doc-1",
        status: "rendering",
        progress: 0.25,
        message: "已完成第 1/8 段渲染。",
      },
    });

    expect(resolved.percent).toBe(64);
    expect(resolved.message).toBe("第 3/5 段处理完成。 (3/5 段)");
    expect(resolved.source).toBe("tts");
  });

  it("TTS 已结束时不再回退 render job，而是显示空闲态", () => {
    const resolved = resolveWorkspaceProgressState({
      inferenceProgress: {
        task_id: "tts-1",
        status: "completed",
        progress: 1,
        message: "推理完成。",
        cancel_requested: false,
        current_segment: 5,
        total_segments: 5,
        result_id: "result-1",
        updated_at: "2026-04-06T00:00:00.000Z",
      },
      renderJob: {
        job_id: "job-1",
        document_id: "doc-1",
        status: "committing",
        progress: 0.9,
        message: "正在提交编辑版本。",
      },
    });

    expect(resolved.percent).toBe(0);
    expect(resolved.message).toBe("等待中...");
    expect(resolved.source).toBe("idle");
  });
});
