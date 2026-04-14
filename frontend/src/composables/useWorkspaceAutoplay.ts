import { computed, ref } from "vue";

// Workspace 级临时前端状态：控制单击选段是否自动跳转并播放。
const autoPlayEnabled = ref(true);

export function useWorkspaceAutoplay() {
  function setAutoPlayEnabled(enabled: boolean) {
    autoPlayEnabled.value = enabled;
  }

  function toggleAutoPlay() {
    autoPlayEnabled.value = !autoPlayEnabled.value;
  }

  return {
    isAutoPlayEnabled: computed(() => autoPlayEnabled.value),
    setAutoPlayEnabled,
    toggleAutoPlay,
  };
}
