import { ref, computed } from "vue";
import type { WorkspaceSegmentTextDraft } from "@/components/workspace/workspace-editor/terminalRegionModel";

const draftTextBySegmentId = ref<Map<string, WorkspaceSegmentTextDraft>>(new Map());
const dirtySegmentIds = ref<Set<string>>(new Set());

export function useWorkspaceLightEdit() {
  const replaceAllDrafts = (
    drafts: Record<string, WorkspaceSegmentTextDraft> | Map<string, WorkspaceSegmentTextDraft>,
  ) => {
    const nextDrafts = drafts instanceof Map ? new Map(drafts) : new Map(Object.entries(drafts));
    draftTextBySegmentId.value = nextDrafts;
    dirtySegmentIds.value = new Set(nextDrafts.keys());
  };

  const setDraft = (segId: string, draft: WorkspaceSegmentTextDraft) => {
    const nextDrafts = new Map(draftTextBySegmentId.value);
    nextDrafts.set(segId, draft);
    replaceAllDrafts(nextDrafts);
  };

  const clearDraft = (segId: string) => {
    const nextDrafts = new Map(draftTextBySegmentId.value);
    nextDrafts.delete(segId);
    replaceAllDrafts(nextDrafts);
  };

  const clearAll = () => {
    replaceAllDrafts({});
  };

  const getDraft = (segId: string): WorkspaceSegmentTextDraft | undefined => {
    return draftTextBySegmentId.value.get(segId);
  };

  const isDirty = (segId: string): boolean => {
    return dirtySegmentIds.value.has(segId);
  };

  return {
    draftTextBySegmentId: computed(() => new Map(draftTextBySegmentId.value)),
    dirtySegmentIds: computed(() => new Set(dirtySegmentIds.value)),
    rerenderSegmentIds: computed(
      () =>
        new Set(
          Array.from(draftTextBySegmentId.value.entries())
            .filter(([, draft]) => draft.stem.length > 0)
            .map(([segmentId]) => segmentId),
        ),
    ),
    dirtyCount: computed(() => dirtySegmentIds.value.size),
    setDraft,
    clearDraft,
    clearAll,
    replaceAllDrafts,
    getDraft,
    isDirty,
  };
}
