import { describe, expect, it } from "vitest";

import {
  buildSessionHeadText,
  isExportBlockedByRenderJob,
  isRelativeTargetDir,
  resolveNavbarRuntimeHint,
  resolveWorkspaceEntryAction,
} from "../src/components/workspace/sessionHandoff";

describe("sessionHandoff", () => {
  it("空输入稿不会触发 workspace 初始化动作", () => {
    expect(
      resolveWorkspaceEntryAction({
        sessionStatus: "empty",
        hasInputText: false,
        inputSource: "manual",
        draftRevision: 3,
        lastSentToSessionRevision: null,
        sourceDraftRevision: null,
      }),
    ).toBe("idle");
  });

  it("empty 会话且存在输入稿时进入 initialize", () => {
    expect(
      resolveWorkspaceEntryAction({
        sessionStatus: "empty",
        hasInputText: true,
        inputSource: "manual",
        draftRevision: 3,
        lastSentToSessionRevision: 1,
        sourceDraftRevision: null,
      }),
    ).toBe("initialize");
  });

  it("ready 会话且输入稿版本领先时进入 rebuild", () => {
    expect(
      resolveWorkspaceEntryAction({
        sessionStatus: "ready",
        hasInputText: true,
        inputSource: "manual",
        draftRevision: 5,
        lastSentToSessionRevision: 4,
        sourceDraftRevision: 4,
      }),
    ).toBe("rebuild");
  });

  it("输入稿与会话版本一致时不触发 rebuild", () => {
    expect(
      resolveWorkspaceEntryAction({
        sessionStatus: "ready",
        hasInputText: true,
        inputSource: "session",
        draftRevision: 5,
        lastSentToSessionRevision: 5,
        sourceDraftRevision: 5,
      }),
    ).toBe("idle");
  });

  it("workspace 镜像稿不会被误判成需要 rebuild 的新输入稿", () => {
    expect(
      resolveWorkspaceEntryAction({
        sessionStatus: "ready",
        hasInputText: true,
        inputSource: "workspace",
        draftRevision: 7,
        lastSentToSessionRevision: 5,
        sourceDraftRevision: 5,
      }),
    ).toBe("idle");
  });

  it("buildSessionHeadText 会按 order_key 顺序拼接当前 session 正文", () => {
    expect(
      buildSessionHeadText([
        { segment_id: "seg-2", raw_text: "第二句", order_key: 2 },
        { segment_id: "seg-1", raw_text: "第一句。", order_key: 1 },
      ]),
    ).toBe("第一句。第二句");
  });

  it("target_dir 只允许相对路径", () => {
    expect(isRelativeTargetDir("exports/demo")).toBe(true);
    expect(isRelativeTargetDir("nested/output")).toBe(true);
    expect(isRelativeTargetDir("C:/exports/demo")).toBe(false);
    expect(isRelativeTargetDir("..\\escape")).toBe(false);
    expect(isRelativeTargetDir("/root/out")).toBe(false);
  });

  it("顶栏运行态提示优先显示暂停，其次推理中，再其次导出中", () => {
    expect(
      resolveNavbarRuntimeHint({
        currentRenderJob: {
          job_id: "job-1",
          status: "paused",
          progress: 0.5,
          message: "paused",
        },
        currentExportJob: {
          export_job_id: "export-1",
          document_id: "doc-1",
          document_version: 2,
          timeline_manifest_id: "timeline-1",
          export_kind: "segments",
          status: "exporting",
          target_dir: "exports/demo",
          overwrite_policy: "fail",
          progress: 0.5,
          message: "halfway",
          output_manifest: null,
          staging_dir: null,
          updated_at: "2026-04-07T00:00:00Z",
        },
      }),
    ).toBe("已暂停");

    expect(
      resolveNavbarRuntimeHint({
        currentRenderJob: {
          job_id: "job-2",
          status: "rendering",
          progress: 0.2,
          message: "running",
        },
        currentExportJob: null,
      }),
    ).toBe("推理中");

    expect(
      resolveNavbarRuntimeHint({
        currentRenderJob: null,
        currentExportJob: {
          export_job_id: "export-2",
          document_id: "doc-1",
          document_version: 2,
          timeline_manifest_id: "timeline-1",
          export_kind: "segments",
          status: "exporting",
          target_dir: "exports/demo",
          overwrite_policy: "fail",
          progress: 0.5,
          message: "halfway",
          output_manifest: null,
          staging_dir: null,
          updated_at: "2026-04-07T00:00:00Z",
        },
      }),
    ).toBe("导出中");

    expect(
      resolveNavbarRuntimeHint({
        currentRenderJob: null,
        currentExportJob: null,
      }),
    ).toBeNull();
  });

  it("导出门禁只在推理运行中阻断，paused 不阻断", () => {
    expect(isExportBlockedByRenderJob(null)).toBe(false);
    expect(
      isExportBlockedByRenderJob({
        job_id: "job-paused",
        status: "paused",
        progress: 0.4,
        message: "paused",
      }),
    ).toBe(false);
    expect(
      isExportBlockedByRenderJob({
        job_id: "job-running",
        status: "rendering",
        progress: 0.2,
        message: "running",
      }),
    ).toBe(true);
    expect(
      isExportBlockedByRenderJob({
        job_id: "job-queue",
        status: "queued",
        progress: 0,
        message: "queued",
      }),
    ).toBe(true);
  });
});
