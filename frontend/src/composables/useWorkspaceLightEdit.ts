import { ref, computed } from "vue";

const draftTextBySegmentId = ref<Map<string, string>>(new Map());
const dirtySegmentIds = ref<Set<string>>(new Set());

export function useWorkspaceLightEdit() {
  const replaceAllDrafts = (
    drafts: Record<string, string> | Map<string, string>,
  ) => {
    const nextDrafts = drafts instanceof Map ? new Map(drafts) : new Map(Object.entries(drafts));
    draftTextBySegmentId.value = nextDrafts;
    dirtySegmentIds.value = new Set(nextDrafts.keys());
  };

  const setDraft = (segId: string, text: string) => {
    const nextDrafts = new Map(draftTextBySegmentId.value);
    nextDrafts.set(segId, text);
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

  const getDraft = (segId: string): string | undefined => {
    return draftTextBySegmentId.value.get(segId);
  };

  const isDirty = (segId: string): boolean => {
    return dirtySegmentIds.value.has(segId);
  };

  return {
    draftTextBySegmentId: computed(() => new Map(draftTextBySegmentId.value)),
    dirtySegmentIds: computed(() => new Set(dirtySegmentIds.value)),
    dirtyCount: computed(() => dirtySegmentIds.value.size),
    setDraft,
    clearDraft,
    clearAll,
    replaceAllDrafts,
    getDraft,
    isDirty,
  };
}
