import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  runtimeStateMock,
  inferenceRuntimeMock,
  parameterPanelMock,
  workspaceExitBridgeMock,
  editSessionApiMock,
  systemApiMock,
  elementPlusMock,
} = vi.hoisted(() => {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { ref } = require("vue");

  const activeInferenceState = {
    task_id: "task-1",
    status: "cancelling",
    progress: 0.3,
    message: "cancelling",
    cancel_requested: true,
    current_segment: 1,
    total_segments: 3,
    result_id: null,
    updated_at: "2026-04-11T10:00:00.000Z",
  };

  return {
    runtimeStateMock: {
      currentRenderJob: ref(null),
    },
    inferenceRuntimeMock: {
      progress: ref({
        task_id: null,
        status: "idle",
        progress: 0,
        message: "",
        cancel_requested: false,
        current_segment: null,
        total_segments: null,
        result_id: null,
        updated_at: "1970-01-01T00:00:00.000Z",
      }),
      requestForcePause: vi.fn().mockResolvedValue({
        accepted: true,
        state: activeInferenceState,
      }),
      refreshProgress: vi.fn().mockResolvedValue({
        ...activeInferenceState,
        status: "cancelled",
        message: "cancelled",
      }),
    },
    parameterPanelMock: {
      hasDirty: ref(false),
      submitDraft: vi.fn().mockResolvedValue(undefined),
      discardDraft: vi.fn(),
    },
    workspaceExitBridgeMock: {
      hasPendingTextChanges: vi.fn(() => false),
      flushDraft: vi.fn(),
      clearDraft: vi.fn(),
    },
    editSessionApiMock: {
      pauseRenderJob: vi.fn().mockResolvedValue(undefined),
      waitForRenderJobTerminal: vi.fn().mockResolvedValue("paused"),
    },
    systemApiMock: {
      prepareExit: vi.fn().mockResolvedValue({
        status: "prepared",
        launcher_exit_requested: true,
        active_render_job_status: null,
        inference_status: "idle",
      }),
    },
    elementPlusMock: {
      confirm: vi.fn(),
      success: vi.fn(),
      info: vi.fn(),
      error: vi.fn(),
    },
  };
});

vi.mock("@/composables/useRuntimeState", () => ({
  useRuntimeState: () => runtimeStateMock,
}));

vi.mock("@/composables/useInferenceRuntime", () => ({
  useInferenceRuntime: () => inferenceRuntimeMock,
}));

vi.mock("@/composables/useParameterPanel", () => ({
  useParameterPanel: () => parameterPanelMock,
}));

vi.mock(
  "@/composables/useWorkspaceExitBridge",
  () => ({
    useWorkspaceExitBridge: () => workspaceExitBridgeMock,
  }),
  { virtual: true },
);

vi.mock("@/api/editSession", () => editSessionApiMock);
vi.mock("@/api/system", () => systemApiMock);
vi.mock("element-plus", () => ({
  ElMessageBox: {
    confirm: elementPlusMock.confirm,
  },
  ElMessage: {
    success: elementPlusMock.success,
    info: elementPlusMock.info,
    error: elementPlusMock.error,
  },
}));

describe("useAppExit", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    runtimeStateMock.currentRenderJob.value = null;
    inferenceRuntimeMock.progress.value = {
      task_id: null,
      status: "idle",
      progress: 0,
      message: "",
      cancel_requested: false,
      current_segment: null,
      total_segments: null,
      result_id: null,
      updated_at: "1970-01-01T00:00:00.000Z",
    };
    parameterPanelMock.hasDirty.value = false;
    workspaceExitBridgeMock.hasPendingTextChanges.mockReturnValue(false);
    editSessionApiMock.waitForRenderJobTerminal.mockResolvedValue("paused");
    systemApiMock.prepareExit.mockResolvedValue({
      status: "prepared",
      launcher_exit_requested: true,
      active_render_job_status: null,
      inference_status: "idle",
    });
    elementPlusMock.confirm.mockResolvedValue("confirm");
  });

  it("没有未决修改时直接走退出链路", async () => {
    const { useAppExit } = await import("../src/composables/useAppExit");
    const appExit = useAppExit();

    await appExit.requestExit();

    expect(elementPlusMock.confirm).not.toHaveBeenCalled();
    expect(systemApiMock.prepareExit).toHaveBeenCalledTimes(1);
  });

  it("有未决修改时会先弹三选一确认", async () => {
    workspaceExitBridgeMock.hasPendingTextChanges.mockReturnValue(true);
    elementPlusMock.confirm.mockRejectedValue("close");

    const { useAppExit } = await import("../src/composables/useAppExit");
    const appExit = useAppExit();

    await appExit.requestExit();

    expect(elementPlusMock.confirm).toHaveBeenCalledTimes(1);
    expect(editSessionApiMock.pauseRenderJob).not.toHaveBeenCalled();
    expect(systemApiMock.prepareExit).not.toHaveBeenCalled();
  });

  it("选择保存修改并退出时会先暂停任务，再保存文本，再提交参数，再调 prepare-exit", async () => {
    const sequence: string[] = [];
    workspaceExitBridgeMock.hasPendingTextChanges.mockReturnValue(true);
    parameterPanelMock.hasDirty.value = true;
    runtimeStateMock.currentRenderJob.value = {
      job_id: "job-1",
      status: "rendering",
      progress: 0.5,
      message: "running",
    };
    editSessionApiMock.pauseRenderJob.mockImplementation(async () => {
      sequence.push("pause-render-job");
    });
    editSessionApiMock.waitForRenderJobTerminal.mockImplementation(async () => {
      sequence.push("wait-render-job");
      return "paused";
    });
    workspaceExitBridgeMock.flushDraft.mockImplementation(() => {
      sequence.push("flush-draft");
    });
    parameterPanelMock.submitDraft.mockImplementation(async () => {
      sequence.push("submit-parameter-draft");
    });
    systemApiMock.prepareExit.mockImplementation(async () => {
      sequence.push("prepare-exit");
      return {
        status: "prepared",
        launcher_exit_requested: true,
        active_render_job_status: "paused",
        inference_status: "idle",
      };
    });

    const { useAppExit } = await import("../src/composables/useAppExit");
    const appExit = useAppExit();

    await appExit.requestExit();

    expect(sequence).toEqual([
      "pause-render-job",
      "wait-render-job",
      "flush-draft",
      "submit-parameter-draft",
      "prepare-exit",
    ]);
    expect(parameterPanelMock.discardDraft).not.toHaveBeenCalled();
    expect(workspaceExitBridgeMock.clearDraft).not.toHaveBeenCalled();
  });

  it("选择放弃修改并退出时不会提交参数", async () => {
    const sequence: string[] = [];
    workspaceExitBridgeMock.hasPendingTextChanges.mockReturnValue(true);
    parameterPanelMock.hasDirty.value = true;
    runtimeStateMock.currentRenderJob.value = {
      job_id: "job-1",
      status: "rendering",
      progress: 0.5,
      message: "running",
    };
    elementPlusMock.confirm.mockRejectedValue("cancel");
    editSessionApiMock.pauseRenderJob.mockImplementation(async () => {
      sequence.push("pause-render-job");
    });
    editSessionApiMock.waitForRenderJobTerminal.mockImplementation(async () => {
      sequence.push("wait-render-job");
      return "paused";
    });
    systemApiMock.prepareExit.mockImplementation(async () => {
      sequence.push("prepare-exit");
      return {
        status: "prepared",
        launcher_exit_requested: true,
        active_render_job_status: "paused",
        inference_status: "idle",
      };
    });
    workspaceExitBridgeMock.clearDraft.mockImplementation(() => {
      sequence.push("clear-draft");
    });
    parameterPanelMock.discardDraft.mockImplementation(() => {
      sequence.push("discard-parameter-draft");
    });

    const { useAppExit } = await import("../src/composables/useAppExit");
    const appExit = useAppExit();

    await appExit.requestExit();

    expect(parameterPanelMock.submitDraft).not.toHaveBeenCalled();
    expect(sequence).toEqual([
      "pause-render-job",
      "wait-render-job",
      "prepare-exit",
      "clear-draft",
      "discard-parameter-draft",
    ]);
  });

  it("prepare-exit 失败时不会把流程误判为退出成功", async () => {
    systemApiMock.prepareExit.mockRejectedValue(new Error("prepare exit failed"));

    const { useAppExit } = await import("../src/composables/useAppExit");
    const appExit = useAppExit();

    await expect(appExit.requestExit()).rejects.toThrow("prepare exit failed");

    expect(elementPlusMock.error).toHaveBeenCalledTimes(1);
    expect(elementPlusMock.success).not.toHaveBeenCalled();
    expect(elementPlusMock.info).not.toHaveBeenCalled();
    expect(appExit.isExiting.value).toBe(false);
  });
});
