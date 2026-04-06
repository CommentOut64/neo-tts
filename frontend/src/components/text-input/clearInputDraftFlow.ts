export type ClearInputDraftResult =
  | "cancelled"
  | "cleared_draft"
  | "cleared_draft_and_session";

export interface ClearInputDraftFlowOptions {
  confirmClearDraft: () => Promise<void>;
  loadHasSessionContent: () => Promise<boolean>;
  chooseSessionCleanup: () => Promise<boolean>;
  clearDraft: () => void;
  clearSession: () => Promise<void>;
}

export async function runClearInputDraftFlow(
  options: ClearInputDraftFlowOptions,
): Promise<ClearInputDraftResult> {
  try {
    await options.confirmClearDraft();
  } catch {
    return "cancelled";
  }

  const hasSessionContent = await options.loadHasSessionContent();
  if (!hasSessionContent) {
    options.clearDraft();
    return "cleared_draft";
  }

  const shouldClearSession = await options.chooseSessionCleanup();
  if (shouldClearSession) {
    await options.clearSession();
    options.clearDraft();
    return "cleared_draft_and_session";
  }

  options.clearDraft();
  return "cleared_draft";
}
