import type { SessionStatus } from "@/composables/useEditSession";

export type MainActionMode = "init" | "rerender";

export interface ResolveMainActionButtonStateOptions {
  sessionStatus: SessionStatus;
  dirtyCount: number;
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

  return {
    mode: "rerender",
    label: `重推理(${dirtyCount})`,
    disabled: sessionStatus !== "ready" || dirtyCount === 0 || !canMutate,
  };
}
