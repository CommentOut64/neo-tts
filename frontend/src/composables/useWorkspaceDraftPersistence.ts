import type { WorkspaceDraftSnapshot } from "@/utils/workspaceDraftSnapshot";
import {
  WORKSPACE_DRAFT_INDEX_KEY,
  buildWorkspaceDraftStorageKey,
  isWorkspaceDraftCompatible,
  normalizeWorkspaceDraftSnapshot,
  type WorkspaceDraftCompatibilityInput,
} from "@/utils/workspaceDraftSnapshot";

type StorageLike = Storage | null;

function getStorage(): StorageLike {
  if (typeof window === "undefined" || typeof window.localStorage === "undefined") {
    return null;
  }

  return window.localStorage;
}

function readIndex(storage: StorageLike = getStorage()): string[] {
  if (!storage) {
    return [];
  }

  const raw = storage.getItem(WORKSPACE_DRAFT_INDEX_KEY);
  if (!raw) {
    return [];
  }

  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed) || !parsed.every((item) => typeof item === "string")) {
      storage.removeItem(WORKSPACE_DRAFT_INDEX_KEY);
      return [];
    }

    return parsed;
  } catch {
    storage.removeItem(WORKSPACE_DRAFT_INDEX_KEY);
    return [];
  }
}

function writeIndex(documentIds: string[], storage: StorageLike = getStorage()) {
  if (!storage) {
    return;
  }

  if (documentIds.length === 0) {
    storage.removeItem(WORKSPACE_DRAFT_INDEX_KEY);
    return;
  }

  storage.setItem(
    WORKSPACE_DRAFT_INDEX_KEY,
    JSON.stringify([...new Set(documentIds)]),
  );
}

function trackDocumentId(documentId: string, storage: StorageLike = getStorage()) {
  if (!storage) {
    return;
  }

  const nextIds = new Set(readIndex(storage));
  nextIds.add(documentId);
  writeIndex([...nextIds], storage);
}

function untrackDocumentId(documentId: string, storage: StorageLike = getStorage()) {
  if (!storage) {
    return;
  }

  const nextIds = readIndex(storage).filter((id) => id !== documentId);
  writeIndex(nextIds, storage);
}

export function useWorkspaceDraftPersistence() {
  function readSnapshot(documentId: string): WorkspaceDraftSnapshot | null {
    const storage = getStorage();
    if (!storage) {
      return null;
    }

    const raw = storage.getItem(buildWorkspaceDraftStorageKey(documentId));
    if (!raw) {
      return null;
    }

    try {
      const snapshot = normalizeWorkspaceDraftSnapshot(JSON.parse(raw));
      if (!snapshot) {
        clearSnapshot(documentId);
        return null;
      }

      return snapshot;
    } catch {
      clearSnapshot(documentId);
      return null;
    }
  }

  function readCompatibleSnapshot(
    input: WorkspaceDraftCompatibilityInput,
  ): WorkspaceDraftSnapshot | null {
    const snapshot = readSnapshot(input.documentId);
    if (!snapshot) {
      return null;
    }

    return isWorkspaceDraftCompatible(snapshot, input) ? snapshot : null;
  }

  function saveSnapshot(snapshot: WorkspaceDraftSnapshot): boolean {
    const storage = getStorage();
    if (!storage) {
      return false;
    }

    try {
      storage.setItem(
        buildWorkspaceDraftStorageKey(snapshot.documentId),
        JSON.stringify(snapshot),
      );
      trackDocumentId(snapshot.documentId, storage);
      return true;
    } catch (error) {
      console.warn("[workspace] failed to persist local draft snapshot", error);
      return false;
    }
  }

  function clearSnapshot(documentId: string) {
    const storage = getStorage();
    if (!storage) {
      return;
    }

    storage.removeItem(buildWorkspaceDraftStorageKey(documentId));
    untrackDocumentId(documentId, storage);
  }

  function clearAllSnapshots() {
    const storage = getStorage();
    if (!storage) {
      return;
    }

    const documentIds = readIndex(storage);
    documentIds.forEach((documentId) => {
      storage.removeItem(buildWorkspaceDraftStorageKey(documentId));
    });
    storage.removeItem(WORKSPACE_DRAFT_INDEX_KEY);
  }

  return {
    readSnapshot,
    readCompatibleSnapshot,
    saveSnapshot,
    clearSnapshot,
    clearAllSnapshots,
  };
}
