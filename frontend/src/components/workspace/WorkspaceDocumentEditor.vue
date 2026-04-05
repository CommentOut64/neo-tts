<script setup lang="ts">
import { computed } from "vue";
import { useInputDraft } from "@/composables/useInputDraft";

const { text, setText } = useInputDraft();

const editorContent = computed({
  get: () => text.value,
  set: (value: string) => {
    setText(value);
  },
});
</script>

<template>
  <section
    class="flex-1 min-h-[280px] w-full bg-card rounded-card shadow-card border border-border overflow-hidden"
  >
    <div class="px-4 py-3 border-b border-border/70 flex items-center justify-between">
      <div>
        <h3 class="text-sm font-semibold text-foreground">整稿编辑</h3>
        <p class="text-xs text-muted-fg mt-1">直接修改完整文本，应用后重新生成时间线</p>
      </div>
      <div class="text-xs text-muted-fg">
        {{ text.length }} 字
      </div>
    </div>

    <div class="p-4">
      <UEditor
        v-model="editorContent"
        content-type="markdown"
        placeholder="在这里直接编辑整稿内容"
        class="min-h-[320px]"
        :ui="{ base: 'min-h-[320px] p-4 text-sm leading-7' }"
      />
    </div>
  </section>
</template>
