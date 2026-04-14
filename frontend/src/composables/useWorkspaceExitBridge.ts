export interface WorkspaceExitHandlers {
  hasPendingTextChanges: () => boolean;
  flushDraft: () => void;
  clearDraft: () => void;
}

const NOOP_HANDLERS: WorkspaceExitHandlers = {
  hasPendingTextChanges: () => false,
  flushDraft: () => {},
  clearDraft: () => {},
};

let workspaceExitHandlers: WorkspaceExitHandlers = NOOP_HANDLERS;

export function registerWorkspaceExitHandlers(
  handlers: WorkspaceExitHandlers,
): () => void {
  workspaceExitHandlers = handlers;

  return () => {
    if (workspaceExitHandlers === handlers) {
      workspaceExitHandlers = NOOP_HANDLERS;
    }
  };
}

export function useWorkspaceExitBridge(): WorkspaceExitHandlers {
  return workspaceExitHandlers;
}
