import type { SessionStatus } from "@/composables/useEditSession";

export type MainActionMode = "init" | "rerender" | "random_draw" | "apply_reorder";

export interface ResolveMainActionButtonStateOptions {
  sessionStatus: SessionStatus;
  dirtyCount: number;
  hasReorderDraft: boolean;
  canRandomDraw: boolean;
  canInitialize: boolean;
  canMutate: boolean;
}

export interface MainActionButtonState {
  mode: MainActionMode;
  label: string;
  disabled: boolean;
}

export function resolveMainActionButtonState({
  sessionStatus,
  dirtyCount,
  hasReorderDraft,
  canRandomDraw,
  canInitialize,
  canMutate,
}: ResolveMainActionButtonStateOptions): MainActionButtonState {
  if (sessionStatus === "empty") {
    return {
      mode: "init",
      label: "开始生成",
      disabled: !canInitialize || !canMutate,
    };
  }

  if (hasReorderDraft) {
    return {
      mode: "apply_reorder",
      label: "应用重排",
      disabled: sessionStatus !== "ready" || !canMutate,
    };
  }

  if (dirtyCount === 0 && canRandomDraw) {
    return {
      mode: "random_draw",
      label: "重新抽卡",
      disabled: sessionStatus !== "ready" || !canMutate,
    };
  }

  return {
    mode: "rerender",
    label: `重推理(${dirtyCount})`,
    disabled: sessionStatus !== "ready" || dirtyCount === 0 || !canMutate,
  };
}
