import { computed, ref } from "vue";

const lockedSegmentIds = ref<Set<string>>(new Set());
const canMutate = computed(() => true);

export function useRuntimeState() {
  return {
    lockedSegmentIds,
    canMutate,
  };
}
