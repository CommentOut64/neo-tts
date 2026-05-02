<script setup lang="ts">
import type { TtsRegistryMainModelNode } from "@/types/ttsRegistry";

defineProps<{
  items: TtsRegistryMainModelNode[];
  selectedMainModelId: string | null;
}>();

const emit = defineEmits<{
  select: [mainModelId: string];
  create: [];
  edit: [mainModelId: string];
  delete: [mainModelId: string];
}>();
</script>

<template>
  <section class="rounded-card border border-border bg-card p-4 shadow-card dark:border-transparent">
    <div class="flex items-center justify-between gap-3">
      <div>
        <h2 class="text-sm font-semibold text-foreground">主模型</h2>
        <p class="mt-1 text-xs text-muted-fg">左侧列表作为当前 workspace 的主模型入口。</p>
      </div>
      <el-button size="small" type="primary" plain @click="emit('create')">新增主模型</el-button>
    </div>

    <div v-if="items.length === 0" class="mt-4 text-sm text-muted-fg">
      当前工作区还没有主模型。
    </div>

    <div v-else class="mt-4 space-y-2">
      <article
        v-for="item in items"
        :key="item.main_model_id"
        class="rounded-card border px-3 py-3 transition-colors"
        :class="item.main_model_id === selectedMainModelId ? 'border-accent/60 bg-secondary/20' : 'border-border/60 bg-card/60'"
      >
        <button class="w-full text-left" @click="emit('select', item.main_model_id)">
          <div class="flex items-center justify-between gap-3">
            <div class="min-w-0">
              <div class="truncate text-sm font-medium text-foreground">{{ item.display_name }}</div>
              <div class="mt-1 text-xs text-muted-fg">{{ item.main_model_id }}</div>
            </div>
            <span class="text-xs text-muted-fg">{{ item.status }}</span>
          </div>
        </button>
        <div class="mt-3 flex justify-end gap-2">
          <el-button text size="small" @click.stop="emit('edit', item.main_model_id)">编辑</el-button>
          <el-button text size="small" type="danger" @click.stop="emit('delete', item.main_model_id)">删除</el-button>
        </div>
      </article>
    </div>
  </section>
</template>
