import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("vue", async () => {
  const actual = await vi.importActual<typeof import("vue")>("vue");
  return {
    ...actual,
    onBeforeUnmount: vi.fn(),
  };
});

const cleanupInferenceResiduals = vi.fn();
const forcePauseInference = vi.fn();
const getInferenceProgress = vi.fn();
const subscribeInferenceProgress = vi.fn();

vi.mock("@/api/tts", () => ({
  cleanupInferenceResiduals,
  forcePauseInference,
  getInferenceProgress,
  subscribeInferenceProgress,
}));

describe("useInferenceRuntime", () => {
  beforeEach(() => {
    vi.resetModules();
    cleanupInferenceResiduals.mockReset();
    forcePauseInference.mockReset();
    getInferenceProgress.mockReset();
    subscribeInferenceProgress.mockReset();
  });

  it("推理进度 SSE 断线后会释放旧订阅并允许重新连接", async () => {
    const firstUnsubscribe = vi.fn();
    const secondUnsubscribe = vi.fn();
    subscribeInferenceProgress
      .mockReturnValueOnce(firstUnsubscribe)
      .mockReturnValueOnce(secondUnsubscribe);

    const { useInferenceRuntime } = await import("../src/composables/useInferenceRuntime");
    const runtime = useInferenceRuntime();

    runtime.connectProgressStream();

    expect(subscribeInferenceProgress).toHaveBeenCalledTimes(1);

    const firstErrorHandler = subscribeInferenceProgress.mock.calls[0][1];
    firstErrorHandler(new Error("推理进度 SSE 连接异常。"));

    expect(firstUnsubscribe).toHaveBeenCalledTimes(1);
    expect(runtime.isProgressStreamConnected.value).toBe(false);
    expect(runtime.runtimeError.value).toBe("推理进度 SSE 连接异常。");

    runtime.connectProgressStream();

    expect(subscribeInferenceProgress).toHaveBeenCalledTimes(2);

    runtime.disconnectProgressStream();

    expect(secondUnsubscribe).toHaveBeenCalledTimes(1);
  });
});
