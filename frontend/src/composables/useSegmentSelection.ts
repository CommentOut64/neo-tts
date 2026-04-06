import { ref, computed } from "vue";

// Module-level singleton
const selectedSegmentIds = ref<Set<string>>(new Set());
const primarySelectedSegmentId = ref<string | null>(null);
const selectedEdgeId = ref<string | null>(null);

export interface SelectionSnapshot {
  selectedSegmentIds: string[];
  primarySelectedSegmentId: string | null;
  selectedEdgeId: string | null;
}

export function useSegmentSelection() {
  const isSelected = (id: string): boolean => {
    return selectedSegmentIds.value.has(id);
  };

  const isEdgeSelected = (id: string): boolean => {
    return selectedEdgeId.value === id;
  };

  const select = (id: string) => {
    selectedSegmentIds.value.clear();
    selectedSegmentIds.value.add(id);
    primarySelectedSegmentId.value = id;
    selectedEdgeId.value = null;
  };

  const toggleSelect = (id: string) => {
    if (selectedSegmentIds.value.has(id)) {
      selectedSegmentIds.value.delete(id);
      // Change primary if we just deleted the primary
      if (primarySelectedSegmentId.value === id) {
        const remaining = Array.from(selectedSegmentIds.value);
        primarySelectedSegmentId.value =
          remaining.length > 0 ? remaining[remaining.length - 1] : null;
      }
    } else {
      selectedSegmentIds.value.add(id);
      primarySelectedSegmentId.value = id;
    }
    selectedEdgeId.value = null;
  };

  const rangeSelect = (id: string, allIds: string[]) => {
    if (!primarySelectedSegmentId.value) {
      select(id);
      return;
    }

    const startIdx = allIds.indexOf(primarySelectedSegmentId.value);
    const endIdx = allIds.indexOf(id);

    if (startIdx === -1 || endIdx === -1) {
      select(id);
      return;
    }

    const min = Math.min(startIdx, endIdx);
    const max = Math.max(startIdx, endIdx);

    // A standard range select (Shift+Click) usually clears existing outside the range,
    // but here we just replace current selection with the new range.
    selectedSegmentIds.value.clear();
    for (let i = min; i <= max; i++) {
      selectedSegmentIds.value.add(allIds[i]);
    }
    // retain the originally clicked primary, but this could vary by UX rules.
  };

  const clearSelection = () => {
    selectedSegmentIds.value.clear();
    primarySelectedSegmentId.value = null;
    selectedEdgeId.value = null;
  };

  const selectEdge = (id: string) => {
    selectedSegmentIds.value.clear();
    primarySelectedSegmentId.value = null;
    selectedEdgeId.value = id;
  };

  const captureSelection = (): SelectionSnapshot => {
    return {
      selectedSegmentIds: Array.from(selectedSegmentIds.value),
      primarySelectedSegmentId: primarySelectedSegmentId.value,
      selectedEdgeId: selectedEdgeId.value,
    };
  };

  const restoreSelection = (snapshot: SelectionSnapshot) => {
    selectedSegmentIds.value = new Set(snapshot.selectedSegmentIds);
    primarySelectedSegmentId.value = snapshot.primarySelectedSegmentId;
    selectedEdgeId.value = snapshot.selectedEdgeId;
  };

  return {
    selectedSegmentIds: computed(() => new Set(selectedSegmentIds.value)), // Expose copy or readonly interface if you prefer
    primarySelectedSegmentId: computed(() => primarySelectedSegmentId.value),
    selectedEdgeId,
    isSelected,
    isEdgeSelected,
    select,
    toggleSelect,
    rangeSelect,
    clearSelection,
    selectEdge,
    captureSelection,
    restoreSelection,
  };
}
