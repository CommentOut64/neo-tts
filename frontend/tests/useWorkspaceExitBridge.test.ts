import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  runtimeStateMock,
  inferenceRuntimeMock,
  parameterPanelMock,
  editSessionApiMock,
  systemApiMock,
  elementPlusMock,
} = vi.hoisted(() => {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { ref } = require("vue");

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
        state: {
          task_id: "task-1",
          status: "cancelled",
          progress: 1,
          message: "cancelled",
          cancel_requested: false,
          current_segment: null,
          total_segments: null,
          result_id: null,
          updated_at: "2026-04-11T10:00:00.000Z",
        },
      }),
      refreshProgress: vi.fn().mockResolvedValue({
        task_id: "task-1",
        status: "cancelled",
        progress: 1,
        message: "cancelled",
        cancel_requested: false,
        current_segment: null,
        total_segments: null,
        result_id: null,
        updated_at: "2026-04-11T10:00:00.000Z",
      }),
    },
    parameterPanelMock: {
      hasDirty: ref(false),
      submitDraft: vi.fn().mockResolvedValue(undefined),
      discardDraft: vi.fn(),
    },
    editSessionApiMock: {
      pauseRenderJob: vi.fn().mockResolvedValue(undefined),
      waitForRenderJobTerminal: vi.fn().mockResolvedValue("paused"),
    },
    systemApiMock: {
      prepareExit: vi.fn().mockResolvedValue({
        status: "prepared",
        launcher_exit_requested: true,
        active_render_job_status: "paused",
        inference_status: "idle",
      }),
    },
    elementPlusMock: {
      confirm: vi.fn().mockResolvedValue("confirm"),
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

describe("useWorkspaceExitBridge", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    parameterPanelMock.hasDirty.value = false;
    runtimeStateMock.currentRenderJob.value = null;
    elementPlusMock.confirm.mockResolvedValue("confirm");
    systemApiMock.prepareExit.mockResolvedValue({
      status: "prepared",
      launcher_exit_requested: true,
      active_render_job_status: "paused",
      inference_status: "idle",
    });
  });

  it("workspace host 可注册 hasPendingTextChanges / flushDraft / clearDraft", async () => {
    const { registerWorkspaceExitHandlers, useWorkspaceExitBridge } = await import(
      "../src/composables/useWorkspaceExitBridge"
    );
    const flushDraft = vi.fn();
    const clearDraft = vi.fn();
    const unregister = registerWorkspaceExitHandlers({
      hasPendingTextChanges: () => true,
      flushDraft,
      clearDraft,
    });

    expect(useWorkspaceExitBridge().hasPendingTextChanges()).toBe(true);

    unregister();

    expect(useWorkspaceExitBridge().hasPendingTextChanges()).toBe(false);
    expect(() => useWorkspaceExitBridge().flushDraft()).not.toThrow();
    expect(() => useWorkspaceExitBridge().clearDraft()).not.toThrow();
  });

  it("退出编排器在 save_and_exit 时调用 flushDraft", async () => {
    const sequence: string[] = [];
    const { registerWorkspaceExitHandlers } = await import(
      "../src/composables/useWorkspaceExitBridge"
    );
    const unregister = registerWorkspaceExitHandlers({
      hasPendingTextChanges: () => true,
      flushDraft: () => {
        sequence.push("flush-draft");
      },
      clearDraft: () => {
        sequence.push("clear-draft");
      },
    });
    parameterPanelMock.hasDirty.value = true;
    parameterPanelMock.submitDraft.mockImplementation(async () => {
      sequence.push("submit-parameter-draft");
    });
    systemApiMock.prepareExit.mockImplementation(async () => {
      sequence.push("prepare-exit");
      return {
        status: "prepared",
        launcher_exit_requested: true,
        active_render_job_status: null,
        inference_status: "idle",
      };
    });

    const { useAppExit } = await import("../src/composables/useAppExit");
    await useAppExit().requestExit();

    expect(sequence).toEqual([
      "flush-draft",
      "submit-parameter-draft",
      "prepare-exit",
    ]);
    unregister();
  });

  it("退出编排器在 discard_and_exit 成功后才调用 clearDraft", async () => {
    const sequence: string[] = [];
    const { registerWorkspaceExitHandlers } = await import(
      "../src/composables/useWorkspaceExitBridge"
    );
    const unregister = registerWorkspaceExitHandlers({
      hasPendingTextChanges: () => true,
      flushDraft: () => {
        sequence.push("flush-draft");
      },
      clearDraft: () => {
        sequence.push("clear-draft");
      },
    });
    parameterPanelMock.hasDirty.value = true;
    elementPlusMock.confirm.mockRejectedValue("cancel");
    systemApiMock.prepareExit.mockImplementation(async () => {
      sequence.push("prepare-exit");
      return {
        status: "prepared",
        launcher_exit_requested: true,
        active_render_job_status: null,
        inference_status: "idle",
      };
    });
    parameterPanelMock.discardDraft.mockImplementation(() => {
      sequence.push("discard-parameter-draft");
    });

    const { useAppExit } = await import("../src/composables/useAppExit");
    await useAppExit().requestExit();

    expect(sequence).toEqual([
      "prepare-exit",
      "clear-draft",
      "discard-parameter-draft",
    ]);
    unregister();
  });
});
