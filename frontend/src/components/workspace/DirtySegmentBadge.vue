<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  isDirty?: boolean;
}>();
</script>

<template>
  <span
    v-show="isDirty"
    class="ml-1.5 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-500/10 text-amber-500 border border-amber-500/20"
    title="已修改，待重推理"
  >
    待重推理
  </span>
</template>
