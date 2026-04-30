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
    expect(resolved.message).toBe("正在生成语音 (3/5 段)");
    expect(resolved.source).toBe("tts");
  });

  it("即使 RenderJob 仍处于 preparing，已进入 inferencing 的 TTS 也应优先显示", () => {
    const resolved = resolveWorkspaceProgressState({
      inferenceProgress: {
        task_id: "tts-1",
        status: "inferencing",
        progress: 0.4,
        message: "第 2/5 段处理中。",
        cancel_requested: false,
        current_segment: 2,
        total_segments: 5,
        result_id: null,
        updated_at: "2026-04-30T00:00:00.000Z",
      },
      renderJob: {
        job_id: "job-prepare",
        document_id: "doc-1",
        status: "preparing",
        progress: 0.18,
        message: "参考上下文准备中。",
      },
    });

    expect(resolved.percent).toBe(40);
    expect(resolved.message).toBe("正在生成语音 (2/5 段)");
    expect(resolved.source).toBe("tts");
  });

  it("TTS 已结束且 RenderJob 在提交阶段时显示 100% 同步中", () => {
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

    expect(resolved.percent).toBe(100);
    expect(resolved.message).toBe("生成完成，正在同步...");
    expect(resolved.source).toBe("tts");
  });

  it("prepare 阶段在 inference runtime 尚未就绪时回退到通用加载进度", () => {
    const resolved = resolveWorkspaceProgressState({
      inferenceProgress: {
        task_id: null,
        status: "idle",
        progress: 0,
        message: "",
        cancel_requested: false,
        current_segment: null,
        total_segments: null,
        result_id: null,
        updated_at: "2026-04-06T00:00:00.000Z",
      },
      renderJob: {
        job_id: "job-prepare",
        document_id: "doc-1",
        status: "preparing",
        progress: 0.12,
        message: "参考上下文准备中。",
      },
    });

    expect(resolved.percent).toBe(0);
    expect(resolved.message).toBe("加载中...（首次推理耗时可能较长，请耐心等待）");
    expect(resolved.source).toBe("idle");
  });

  it("inference runtime 在 0% preparing 时保持加载态", () => {
    const resolved = resolveWorkspaceProgressState({
      inferenceProgress: {
        task_id: "tts-prepare",
        status: "preparing",
        progress: 0,
        message: "参考上下文准备中。",
        cancel_requested: false,
        current_segment: 0,
        total_segments: 5,
        result_id: null,
        updated_at: "2026-04-19T00:00:00.000Z",
      },
      renderJob: {
        job_id: "job-prepare",
        document_id: "doc-1",
        status: "preparing",
        progress: 0.18,
        message: "参考上下文准备中。",
      },
    });

    expect(resolved.percent).toBe(0);
    expect(resolved.message).toBe("加载中...（首次推理耗时可能较长，请耐心等待）");
    expect(resolved.source).toBe("idle");
  });

  it("一旦 preparing 已出现非零进度，就不再回退到加载态", () => {
    const resolved = resolveWorkspaceProgressState({
      inferenceProgress: {
        task_id: "tts-prepare",
        status: "preparing",
        progress: 0.64,
        message: "参考上下文准备中。",
        cancel_requested: false,
        current_segment: 1,
        total_segments: 5,
        result_id: null,
        updated_at: "2026-04-19T00:00:00.000Z",
      },
      renderJob: {
        job_id: "job-prepare",
        document_id: "doc-1",
        status: "preparing",
        progress: 0.18,
        message: "参考上下文准备中。",
      },
    });

    expect(resolved.percent).toBe(64);
    expect(resolved.message).toBe("正在生成语音 (1/5 段)");
    expect(resolved.source).toBe("tts");
  });
});
