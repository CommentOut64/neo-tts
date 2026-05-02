<script setup lang="ts">
import type { TtsRegistryPresetNode } from "@/types/ttsRegistry";

defineProps<{
  items: TtsRegistryPresetNode[];
  supportsPresets: boolean;
  allowDelete?: boolean;
}>();

const emit = defineEmits<{
  create: [];
  edit: [presetId: string];
  delete: [presetId: string];
}>();
</script>

<template>
  <section class="rounded-card border border-border bg-card p-4 shadow-card dark:border-transparent">
    <div class="flex items-center justify-between gap-3">
      <div>
        <h2 class="text-sm font-semibold text-foreground">预设</h2>
        <p class="mt-1 text-xs text-muted-fg">当前子模型下的预设列表与后续 CRUD 入口。</p>
      </div>
      <el-button
        v-if="supportsPresets"
        size="small"
        type="primary"
        plain
        @click="emit('create')"
      >
        新增预设
      </el-button>
    </div>

    <div v-if="!supportsPresets" class="mt-4 text-sm text-muted-fg">
      当前 family 不显式暴露 preset 列表。
    </div>

    <div v-else-if="items.length === 0" class="mt-4 text-sm text-muted-fg">
      当前子模型下还没有预设。
    </div>

    <div v-else class="mt-4 space-y-2">
      <article
        v-for="item in items"
        :key="item.preset_id"
        class="rounded-card border border-border/60 bg-card/60 px-3 py-3"
      >
        <div class="flex items-center justify-between gap-3">
          <div class="min-w-0">
            <div class="truncate text-sm font-medium text-foreground">{{ item.display_name }}</div>
            <div class="mt-1 text-xs text-muted-fg">{{ item.preset_id }} / {{ item.kind }}</div>
          </div>
          <span class="text-xs text-muted-fg">{{ item.status }}</span>
        </div>
        <div class="mt-3 flex justify-end gap-2">
          <el-button text size="small" @click.stop="emit('edit', item.preset_id)">编辑</el-button>
          <el-button
            v-if="allowDelete !== false"
            text
            size="small"
            type="danger"
            @click.stop="emit('delete', item.preset_id)"
          >
            删除
          </el-button>
        </div>
      </article>
    </div>
  </section>
</template>
