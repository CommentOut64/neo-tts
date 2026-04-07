import { ref } from "vue";

const exportDialogVisible = ref(false);

export function useWorkspaceDialogState() {
  function openExportDialog() {
    exportDialogVisible.value = true;
  }

  function closeExportDialog() {
    exportDialogVisible.value = false;
  }

  return {
    exportDialogVisible,
    openExportDialog,
    closeExportDialog,
  };
}
