<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { useRouter } from "vue-router";

import {
  createRegistryWorkspace,
  fetchRegistryAdapters,
  fetchRegistryWorkspaces,
} from "@/api/ttsRegistry";
import {
  buildModelWorkspaceRouteLocation,
  buildNextWorkspaceDraft,
} from "@/features/model-center/workspaceRouting";
import type { TtsRegistryAdapterDefinition, TtsRegistryWorkspaceSummary } from "@/types/ttsRegistry";

const WORKSPACES_ENDPOINT = "/v1/tts-registry/workspaces";
const ADAPTERS_ENDPOINT = "/v1/tts-registry/adapters";

const router = useRouter();

const loading = ref(false);
const isCreatingWorkspace = ref(false);
const adapters = ref<TtsRegistryAdapterDefinition[]>([]);
const workspaces = ref<TtsRegistryWorkspaceSummary[]>([]);

async function loadModelHub() {
  loading.value = true;
  try {
    const [nextAdapters, nextWorkspaces] = await Promise.all([
      fetchRegistryAdapters(),
      fetchRegistryWorkspaces(),
    ]);
    adapters.value = nextAdapters;
    workspaces.value = nextWorkspaces;
  } finally {
    loading.value = false;
  }
}

function openWorkspace(workspace: TtsRegistryWorkspaceSummary) {
  void router.push(buildModelWorkspaceRouteLocation(workspace));
}

async function createWorkspace() {
  const draft = buildNextWorkspaceDraft(workspaces.value);
  isCreatingWorkspace.value = true;
  try {
    const created = await createRegistryWorkspace({
      adapter_id: "external_http_tts",
      family_id: "external_http_tts_default",
      display_name: draft.display_name,
      slug: draft.slug,
    });
    await loadModelHub();
    openWorkspace(created);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "创建模型工作区失败");
  } finally {
    isCreatingWorkspace.value = false;
  }
}

onMounted(loadModelHub);
</script>

<template>
  <div class="mx-auto max-w-[1440px] px-8 py-8">
    <div class="mb-6 flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-bold text-foreground">模型中心</h1>
        <p class="mt-1 text-sm text-muted-fg">
          当前工作区导航基于 {{ WORKSPACES_ENDPOINT }} 的摘要路由字段；adapter/family 元数据仍由 {{ ADAPTERS_ENDPOINT }} 提供。
        </p>
        <p class="mt-1 text-xs text-muted-fg">
          当前已发现 {{ adapters.length }} 个 adapter，{{ workspaces.length }} 个 workspace。
        </p>
      </div>
      <el-button type="primary" :loading="isCreatingWorkspace" @click="createWorkspace">
        添加模型工作区
      </el-button>
    </div>

    <section class="rounded-card border border-border bg-card p-4 shadow-card dark:border-transparent">
      <h2 class="mb-3 text-sm font-semibold text-foreground">工作区</h2>
      <div v-if="loading" class="text-sm text-muted-fg">
        正在读取模型工作区...
      </div>
      <div v-else-if="workspaces.length === 0" class="text-sm text-muted-fg">
        暂无模型工作区
      </div>
      <ul v-else class="space-y-2">
        <li
          v-for="workspace in workspaces"
          :key="workspace.workspace_id"
          class="rounded-card border border-border/70 bg-card/60 transition-colors hover:border-accent/60 hover:bg-secondary/20"
        >
          <button
            class="flex w-full items-center justify-between gap-4 px-3 py-3 text-left"
            @click="openWorkspace(workspace)"
          >
            <div class="min-w-0">
              <div class="truncate text-sm font-medium text-foreground">{{ workspace.display_name }}</div>
              <div class="mt-1 text-xs text-muted-fg">
                {{ workspace.family_display_name }} / {{ workspace.slug }}
              </div>
            </div>
            <div class="shrink-0 text-xs text-muted-fg">
              {{ workspace.status }}
            </div>
          </button>
        </li>
      </ul>
    </section>
  </div>
</template>
