import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const onBeforeUnmountCallbacks: Array<() => void> = [];

vi.mock("vue", async () => {
  const actual = await vi.importActual<typeof import("vue")>("vue");
  return {
    ...actual,
    onBeforeUnmount: vi.fn((callback: () => void) => {
      onBeforeUnmountCallbacks.push(callback);
    }),
  };
});

const cleanupInferenceResiduals = vi.fn();
const forcePauseInference = vi.fn();
const getInferenceProgress = vi.fn();
const subscribeInferenceProgress = vi.fn();
const idleProgress = {
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

vi.mock("@/api/tts", () => ({
  cleanupInferenceResiduals,
  forcePauseInference,
  getInferenceProgress,
  subscribeInferenceProgress,
}));

describe("useInferenceRuntime", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.resetModules();
    onBeforeUnmountCallbacks.length = 0;
    cleanupInferenceResiduals.mockReset();
    forcePauseInference.mockReset();
    getInferenceProgress.mockReset();
    getInferenceProgress.mockResolvedValue(idleProgress);
    subscribeInferenceProgress.mockReset();
  });

  afterEach(() => {
    while (onBeforeUnmountCallbacks.length > 0) {
      onBeforeUnmountCallbacks.pop()?.();
    }
    vi.clearAllTimers();
    vi.useRealTimers();
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

    await vi.advanceTimersByTimeAsync(800);

    expect(subscribeInferenceProgress).toHaveBeenCalledTimes(2);

    runtime.disconnectProgressStream();

    expect(secondUnsubscribe).toHaveBeenCalledTimes(1);
  });

  it("共享进度流只有在最后一个消费者卸载时才会真正断开", async () => {
    const unsubscribeImpl = vi.fn();
    subscribeInferenceProgress.mockReturnValue(unsubscribeImpl);

    const { useInferenceRuntime } = await import("../src/composables/useInferenceRuntime");
    const appRuntime = useInferenceRuntime("App");
    useInferenceRuntime("RenderJobProgressBar");

    appRuntime.connectProgressStream("test");
    expect(subscribeInferenceProgress).toHaveBeenCalledTimes(1);

    onBeforeUnmountCallbacks[0]?.();
    expect(unsubscribeImpl).not.toHaveBeenCalled();

    onBeforeUnmountCallbacks[1]?.();
    expect(unsubscribeImpl).toHaveBeenCalledTimes(1);
  });
});
