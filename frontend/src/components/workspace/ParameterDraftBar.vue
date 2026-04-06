<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  scope: "session" | "segment" | "batch" | "edge";
  hasDirty: boolean;
  isSubmitting: boolean;
}>();

const emit = defineEmits<{
  submit: [];
  discard: [];
}>();

const submitLabel = computed(() => "提交参数");
</script>

<template>
  <section class="bg-card rounded-card p-4 shadow-card">
    <div class="flex items-center justify-between gap-3">
      <p class="text-[12px] text-muted-fg">
        {{ hasDirty ? "当前有未提交的参数草稿" : "当前参数已与后端保持一致" }}
      </p>
      <div class="flex items-center gap-2">
        <el-button size="small" text class="!text-muted-fg" :disabled="!hasDirty || isSubmitting" @click="emit('discard')">
          放弃
        </el-button>
        <el-button size="small" type="primary" :disabled="!hasDirty || isSubmitting" @click="emit('submit')">
          {{ isSubmitting ? "提交中..." : submitLabel }}
        </el-button>
      </div>
    </div>
  </section>
</template>
