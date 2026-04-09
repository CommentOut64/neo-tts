export type ClearInputDraftResult =
  | "cancelled"
  | "cleared_all";

export interface ClearInputDraftFlowOptions {
  confirmClearDraft: () => Promise<void>;
  executeClear: () => Promise<void>;
}

export async function runClearInputDraftFlow(
  options: ClearInputDraftFlowOptions,
): Promise<ClearInputDraftResult> {
  try {
    await options.confirmClearDraft();
  } catch {
    return "cancelled";
  }

  await options.executeClear();
  return "cleared_all";
}
