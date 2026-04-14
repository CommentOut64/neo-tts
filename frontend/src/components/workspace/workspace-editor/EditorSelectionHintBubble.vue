<script setup lang="ts">
defineProps<{
  visible: boolean;
  message: string;
  x: number;
  y: number;
}>();
</script>

<template>
  <Teleport to="body">
    <Transition name="editor-selection-hint">
      <div
        v-if="visible"
        class="editor-selection-hint-bubble"
        :style="{ left: `${x}px`, top: `${y}px` }"
      >
        {{ message }}
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.editor-selection-hint-bubble {
  position: fixed;
  z-index: 80;
  max-width: min(240px, calc(100vw - 24px));
  transform: translate(-50%, 0);
  pointer-events: none;
  border: 1px solid rgba(59, 130, 246, 0.18);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.14);
  padding: 6px 10px;
  color: rgb(37 99 235);
  font-size: 12px;
  line-height: 1.2;
  white-space: nowrap;
  backdrop-filter: blur(8px);
}

.editor-selection-hint-enter-active,
.editor-selection-hint-leave-active {
  transition:
    opacity 0.16s ease,
    transform 0.16s ease;
}

.editor-selection-hint-enter-from,
.editor-selection-hint-leave-to {
  opacity: 0;
  transform: translate(-50%, 4px);
}

.editor-selection-hint-enter-to,
.editor-selection-hint-leave-from {
  opacity: 1;
  transform: translate(-50%, 0);
}

:global(html.dark) .editor-selection-hint-bubble {
  border-color: rgba(96, 165, 250, 0.24);
  background: rgba(15, 23, 42, 0.94);
  box-shadow: 0 14px 30px rgba(2, 6, 23, 0.4);
  color: rgb(147 197 253);
}
</style>
