<script setup lang="ts">
import type { TtsRegistryFamilyDefinition, TtsRegistryWorkspaceSummary } from "@/types/ttsRegistry";

defineProps<{
  workspaceSummary: TtsRegistryWorkspaceSummary | null;
  familyDefinition: TtsRegistryFamilyDefinition | null;
}>();

const emit = defineEmits<{
  back: [];
  editWorkspace: [];
  deleteWorkspace: [];
  importModelPackage: [];
}>();
</script>

<template>
  <div class="mb-6 flex items-start justify-between gap-4">
    <div>
      <h1 class="text-2xl font-bold text-foreground">
        {{ workspaceSummary?.display_name ?? "模型工作区" }}
      </h1>
      <p class="mt-1 text-sm text-muted-fg">
        {{ workspaceSummary?.family_display_name ?? "正在解析 family 信息" }}
        <template v-if="workspaceSummary">
          / {{ workspaceSummary.slug }}
        </template>
      </p>
      <p v-if="familyDefinition" class="mt-1 text-xs text-muted-fg">
        route: /models/{{ familyDefinition.route_slug }}/{{ workspaceSummary?.slug ?? "" }}
      </p>
    </div>
    <div class="flex shrink-0 items-center gap-2">
      <el-button plain @click="emit('back')">返回模型中心</el-button>
      <el-button
        v-if="workspaceSummary?.adapter_id === 'gpt_sovits_local'"
        type="primary"
        plain
        @click="emit('importModelPackage')"
      >
        导入模型包
      </el-button>
      <el-button text @click="emit('editWorkspace')">编辑工作区</el-button>
      <el-button text type="danger" @click="emit('deleteWorkspace')">删除工作区</el-button>
    </div>
  </div>
</template>
