<script setup lang="ts">
import { VideoPlay } from "@element-plus/icons-vue";

defineProps<{
  text: string;
  canSubmit: boolean;
}>();

const emit = defineEmits<{
  submit: [];
}>();
</script>

<template>
  <div
    class="h-full flex flex-col p-6 items-center justify-center bg-card rounded-card shadow-card overflow-hidden"
  >
    <div class="text-center mb-10 w-full max-w-xl">
      <h2 class="text-2xl font-bold text-foreground mb-4">准备就绪</h2>
      <p class="text-muted-fg text-[14px]">
        您的输入稿已被送入会话工作区，请在左侧设定发音人与合成参数
      </p>
    </div>

    <div
      class="w-full max-w-3xl flex-1 flex flex-col min-h-0 bg-secondary/20 rounded-card p-5 overflow-hidden"
    >
      <div
        class="text-xs font-semibold text-muted-fg uppercase tracking-wider mb-3 shrink-0"
      >
        当前文本快照
      </div>
      <div
        class="flex-1 overflow-y-auto w-full border border-dashed border-border rounded-card bg-background p-4 mb-5 text-[14px] text-foreground scrollbar-thin"
      >
        {{ text }}
      </div>

      <div class="flex justify-center shrink-0">
        <el-button
          type="primary"
          size="large"
          class="px-10"
          :icon="VideoPlay"
          :disabled="!canSubmit"
          @click="emit('submit')"
        >
          生成时间线
        </el-button>
      </div>
    </div>
  </div>
</template>
