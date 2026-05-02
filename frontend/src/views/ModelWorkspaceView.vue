<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";

import ModelSchemaForm from "@/components/model-center/ModelSchemaForm.vue";
import {
  fetchAdapterFamilies,
  fetchRegistryWorkspaceTree,
  fetchRegistryWorkspaces,
} from "@/api/ttsRegistry";
import { findWorkspaceSummaryByRoute } from "@/features/model-center/workspaceRouting";
import type {
  TtsRegistryFamilyDefinition,
  TtsRegistryWorkspaceSummary,
  TtsRegistryWorkspaceTree,
} from "@/types/ttsRegistry";

const route = useRoute();
const router = useRouter();

const loading = ref(false);
const errorMessage = ref("");
const workspaceSummary = ref<TtsRegistryWorkspaceSummary | null>(null);
const workspaceTree = ref<TtsRegistryWorkspaceTree | null>(null);
const familyDefinition = ref<TtsRegistryFamilyDefinition | null>(null);

const workspaceSchema = computed(() => familyDefinition.value?.workspace_form_schema ?? []);
const mainModelSchema = computed(() => familyDefinition.value?.main_model_form_schema ?? []);
const submodelSchema = computed(() => familyDefinition.value?.submodel_form_schema ?? []);
const presetSchema = computed(() => familyDefinition.value?.preset_form_schema ?? []);

async function loadWorkspace() {
  const familyRoute = typeof route.params.familyRoute === "string" ? route.params.familyRoute : "";
  const workspaceSlug = typeof route.params.workspaceSlug === "string" ? route.params.workspaceSlug : "";

  loading.value = true;
  errorMessage.value = "";
  workspaceSummary.value = null;
  workspaceTree.value = null;
  familyDefinition.value = null;

  if (!familyRoute.trim() || !workspaceSlug.trim()) {
    errorMessage.value = "模型工作区路由参数缺失，无法加载详情。";
    loading.value = false;
    return;
  }

  try {
    const summaries = await fetchRegistryWorkspaces();
    const matchedWorkspace = findWorkspaceSummaryByRoute(summaries, familyRoute, workspaceSlug);
    if (matchedWorkspace == null) {
      errorMessage.value = `未找到模型工作区：${familyRoute}/${workspaceSlug}`;
      return;
    }

    workspaceSummary.value = matchedWorkspace;
    const [tree, families] = await Promise.all([
      fetchRegistryWorkspaceTree(matchedWorkspace.workspace_id),
      fetchAdapterFamilies(matchedWorkspace.adapter_id),
    ]);
    const matchedFamily =
      families.find((family) => family.family_id === matchedWorkspace.family_id) ?? null;
    if (matchedFamily == null) {
      errorMessage.value = `未找到模型 family 定义：${matchedWorkspace.family_id}`;
      return;
    }

    workspaceTree.value = tree;
    familyDefinition.value = matchedFamily;
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "读取模型工作区失败";
    ElMessage.error(errorMessage.value);
  } finally {
    loading.value = false;
  }
}

function openModelHub() {
  void router.push("/models");
}

watch(
  () => [route.params.familyRoute, route.params.workspaceSlug],
  () => {
    void loadWorkspace();
  },
  { immediate: true },
);
</script>

<template>
  <div class="mx-auto max-w-[1440px] px-8 py-8">
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
      </div>
      <el-button plain @click="openModelHub">返回模型中心</el-button>
    </div>

    <section
      v-if="loading"
      class="rounded-card border border-border bg-card px-5 py-6 text-sm text-muted-fg shadow-card dark:border-transparent"
    >
      正在读取模型工作区详情...
    </section>

    <section
      v-else-if="errorMessage"
      class="rounded-card border border-danger/40 bg-card px-5 py-6 shadow-card dark:border-transparent"
    >
      <h2 class="text-sm font-semibold text-foreground">工作区加载失败</h2>
      <p class="mt-2 text-sm text-danger">{{ errorMessage }}</p>
    </section>

    <div v-else-if="workspaceSummary && workspaceTree && familyDefinition" class="space-y-6">
      <section class="rounded-card border border-border bg-card p-4 shadow-card dark:border-transparent">
        <h2 class="text-sm font-semibold text-foreground">工作区摘要</h2>
        <div class="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div class="rounded-card border border-border/60 px-3 py-3">
            <div class="text-xs text-muted-fg">workspace_id</div>
            <div class="mt-1 break-all text-sm text-foreground">{{ workspaceSummary.workspace_id }}</div>
          </div>
          <div class="rounded-card border border-border/60 px-3 py-3">
            <div class="text-xs text-muted-fg">adapter / family</div>
            <div class="mt-1 text-sm text-foreground">
              {{ workspaceSummary.adapter_id }} / {{ workspaceSummary.family_id }}
            </div>
          </div>
          <div class="rounded-card border border-border/60 px-3 py-3">
            <div class="text-xs text-muted-fg">route</div>
            <div class="mt-1 text-sm text-foreground">
              /models/{{ workspaceSummary.family_route_slug }}/{{ workspaceSummary.slug }}
            </div>
          </div>
          <div class="rounded-card border border-border/60 px-3 py-3">
            <div class="text-xs text-muted-fg">status</div>
            <div class="mt-1 text-sm text-foreground">{{ workspaceSummary.status }}</div>
          </div>
        </div>
      </section>

      <section class="rounded-card border border-border bg-card p-4 shadow-card dark:border-transparent">
        <div class="flex items-center justify-between gap-3">
          <div>
            <h2 class="text-sm font-semibold text-foreground">Schema</h2>
            <p class="mt-1 text-xs text-muted-fg">
              当前 family 使用后端声明式 schema 描述 workspace、main model、submodel 与 preset 的表单结构。
            </p>
          </div>
          <div class="text-xs text-muted-fg">{{ familyDefinition.route_slug }}</div>
        </div>

        <div class="mt-4 space-y-4">
          <div v-if="workspaceSchema.length > 0" class="rounded-card border border-border/60 p-4">
            <h3 class="mb-3 text-sm font-semibold text-foreground">Workspace 字段</h3>
            <ModelSchemaForm :schema="workspaceSchema" />
          </div>

          <div v-if="mainModelSchema.length > 0" class="rounded-card border border-border/60 p-4">
            <h3 class="mb-3 text-sm font-semibold text-foreground">Main Model 字段</h3>
            <ModelSchemaForm :schema="mainModelSchema" />
          </div>

          <div v-if="submodelSchema.length > 0" class="rounded-card border border-border/60 p-4">
            <h3 class="mb-3 text-sm font-semibold text-foreground">Submodel 字段</h3>
            <ModelSchemaForm :schema="submodelSchema" />
          </div>

          <div v-if="presetSchema.length > 0" class="rounded-card border border-border/60 p-4">
            <h3 class="mb-3 text-sm font-semibold text-foreground">Preset 字段</h3>
            <ModelSchemaForm :schema="presetSchema" />
          </div>

          <div
            v-if="
              workspaceSchema.length === 0 &&
              mainModelSchema.length === 0 &&
              submodelSchema.length === 0 &&
              presetSchema.length === 0
            "
            class="text-sm text-muted-fg"
          >
            当前 family 没有声明式 schema 字段。
          </div>
        </div>
      </section>

      <section class="rounded-card border border-border bg-card p-4 shadow-card dark:border-transparent">
        <h2 class="text-sm font-semibold text-foreground">模型树</h2>
        <div v-if="workspaceTree.main_models.length === 0" class="mt-3 text-sm text-muted-fg">
          当前工作区还没有主模型。
        </div>
        <div v-else class="mt-3 space-y-4">
          <article
            v-for="mainModel in workspaceTree.main_models"
            :key="mainModel.main_model_id"
            class="rounded-card border border-border/60 p-4"
          >
            <div class="flex flex-wrap items-center gap-2">
              <h3 class="text-sm font-semibold text-foreground">{{ mainModel.display_name }}</h3>
              <span class="text-xs text-muted-fg">{{ mainModel.main_model_id }}</span>
              <span class="text-xs text-muted-fg">{{ mainModel.status }}</span>
            </div>
            <div class="mt-3 space-y-3">
              <div
                v-for="submodel in mainModel.submodels"
                :key="submodel.submodel_id"
                class="rounded-card border border-border/50 bg-secondary/10 px-3 py-3"
              >
                <div class="flex flex-wrap items-center gap-2">
                  <div class="text-sm font-medium text-foreground">{{ submodel.display_name }}</div>
                  <span class="text-xs text-muted-fg">{{ submodel.submodel_id }}</span>
                  <span class="text-xs text-muted-fg">{{ submodel.status }}</span>
                </div>
                <div class="mt-2 text-xs text-muted-fg">
                  endpoint:
                  {{ submodel.endpoint?.url ?? "未配置" }}
                </div>
                <div class="mt-2 flex flex-wrap gap-2">
                  <span
                    v-for="preset in submodel.presets"
                    :key="preset.preset_id"
                    class="rounded-full border border-border/60 px-2 py-1 text-xs text-foreground"
                  >
                    {{ preset.display_name }} / {{ preset.preset_id }}
                  </span>
                </div>
              </div>
            </div>
          </article>
        </div>
      </section>
    </div>
  </div>
</template>
