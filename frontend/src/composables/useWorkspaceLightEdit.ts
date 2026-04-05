import { ref, computed } from "vue";

const draftTextBySegmentId = ref<Map<string, string>>(new Map());
const dirtySegmentIds = ref<Set<string>>(new Set());

export function useWorkspaceLightEdit() {
  const setDraft = (segId: string, text: string) => {
    draftTextBySegmentId.value.set(segId, text);
    dirtySegmentIds.value.add(segId);

    // trigger reactivity
    dirtySegmentIds.value = new Set(dirtySegmentIds.value);
    draftTextBySegmentId.value = new Map(draftTextBySegmentId.value);
  };

  const clearDraft = (segId: string) => {
    draftTextBySegmentId.value.delete(segId);
    dirtySegmentIds.value.delete(segId);

    // trigger reactivity
    dirtySegmentIds.value = new Set(dirtySegmentIds.value);
    draftTextBySegmentId.value = new Map(draftTextBySegmentId.value);
  };

  const clearAll = () => {
    draftTextBySegmentId.value.clear();
    dirtySegmentIds.value.clear();
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
    getDraft,
    isDirty,
  };
}
