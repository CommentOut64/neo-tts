<script setup lang="ts">
import type { TtsRegistrySubmodelNode } from "@/types/ttsRegistry";

defineProps<{
  items: TtsRegistrySubmodelNode[];
  selectedSubmodelId: string | null;
  allowCreate?: boolean;
  allowDelete?: boolean;
}>();

const emit = defineEmits<{
  select: [submodelId: string];
  create: [];
  edit: [submodelId: string];
  delete: [submodelId: string];
  editSecrets: [submodelId: string];
  checkConnectivity: [submodelId: string];
}>();
</script>

<template>
  <section class="rounded-card border border-border bg-card p-4 shadow-card dark:border-transparent">
    <div class="flex items-center justify-between gap-3">
      <div>
        <h2 class="text-sm font-semibold text-foreground">子模型</h2>
        <p class="mt-1 text-xs text-muted-fg">当前主模型下的子模型列表与基础操作入口。</p>
      </div>
      <el-button v-if="allowCreate !== false" size="small" type="primary" plain @click="emit('create')">新增子模型</el-button>
    </div>

    <div v-if="items.length === 0" class="mt-4 text-sm text-muted-fg">
      当前主模型下还没有子模型。
    </div>

    <div v-else class="mt-4 space-y-2">
      <article
        v-for="item in items"
        :key="item.submodel_id"
        class="rounded-card border px-3 py-3 transition-colors"
        :class="item.submodel_id === selectedSubmodelId ? 'border-accent/60 bg-secondary/20' : 'border-border/60 bg-card/60'"
      >
        <button class="w-full text-left" @click="emit('select', item.submodel_id)">
          <div class="flex items-center justify-between gap-3">
            <div class="min-w-0">
              <div class="truncate text-sm font-medium text-foreground">{{ item.display_name }}</div>
              <div class="mt-1 text-xs text-muted-fg">
                {{ item.submodel_id }} / {{ item.endpoint?.url ?? "未配置 endpoint" }}
              </div>
            </div>
            <span class="text-xs text-muted-fg">{{ item.status }}</span>
          </div>
        </button>
        <div class="mt-3 flex flex-wrap justify-end gap-2">
          <el-button text size="small" @click.stop="emit('edit', item.submodel_id)">编辑</el-button>
          <el-button text size="small" @click.stop="emit('editSecrets', item.submodel_id)">Secrets</el-button>
          <el-button text size="small" @click.stop="emit('checkConnectivity', item.submodel_id)">联通性检查</el-button>
          <el-button
            v-if="allowDelete !== false"
            text
            size="small"
            type="danger"
            @click.stop="emit('delete', item.submodel_id)"
          >
            删除
          </el-button>
        </div>
      </article>
    </div>
  </section>
</template>
