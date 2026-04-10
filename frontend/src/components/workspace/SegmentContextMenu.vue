<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from "vue";

const props = defineProps<{
  visible: boolean;
  x: number;
  y: number;
  segmentId: string | null;
  canDelete: boolean;
}>();

const emit = defineEmits<{
  close: [];
  delete: [segmentId: string];
}>();

const menuRef = ref<HTMLElement | null>(null);
const adjustedX = ref(0);
const adjustedY = ref(0);

function clampPosition() {
  const menuWidth = 160;
  const menuHeight = 44;
  const margin = 8;

  const maxX = window.innerWidth - menuWidth - margin;
  const maxY = window.innerHeight - menuHeight - margin;

  adjustedX.value = Math.max(margin, Math.min(props.x, maxX));
  adjustedY.value = Math.max(margin, Math.min(props.y, maxY));
}

function onClickOutside(event: MouseEvent) {
  if (menuRef.value && !menuRef.value.contains(event.target as Node)) {
    emit("close");
  }
}

function onKeyDown(event: KeyboardEvent) {
  if (event.key === "Escape") {
    emit("close");
  }
}

function handleDelete() {
  if (!props.canDelete || !props.segmentId) {
    return;
  }
  emit("delete", props.segmentId);
}

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      clampPosition();
      document.addEventListener("mousedown", onClickOutside, true);
      document.addEventListener("keydown", onKeyDown, true);
    } else {
      document.removeEventListener("mousedown", onClickOutside, true);
      document.removeEventListener("keydown", onKeyDown, true);
    }
  },
);

onBeforeUnmount(() => {
  document.removeEventListener("mousedown", onClickOutside, true);
  document.removeEventListener("keydown", onKeyDown, true);
});
</script>

<template>
  <Teleport to="body">
    <div
      v-if="visible"
      ref="menuRef"
      class="fixed z-50 min-w-[140px] rounded-lg border border-border bg-card py-1 shadow-lg backdrop-blur"
      :style="{ left: `${adjustedX}px`, top: `${adjustedY}px` }"
    >
      <button
        type="button"
        class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs transition-colors"
        :class="canDelete
          ? 'text-destructive hover:bg-destructive/10 cursor-pointer'
          : 'text-muted-fg/50 cursor-not-allowed'"
        :disabled="!canDelete"
        @click="handleDelete"
      >
        删除此段
      </button>
    </div>
  </Teleport>
</template>
