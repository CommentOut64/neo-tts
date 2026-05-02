<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { useRouter } from "vue-router";

import {
  createRegistryWorkspace,
  deleteRegistryWorkspace,
  fetchAdapterFamilies,
  fetchRegistryAdapters,
  fetchRegistryWorkspaces,
  patchRegistryWorkspace,
} from "@/api/ttsRegistry";
import DeleteConfirmDialog from "@/components/model-center/DeleteConfirmDialog.vue";
import WorkspaceDialog from "@/components/model-center/WorkspaceDialog.vue";
import {
  buildModelWorkspaceRouteLocation,
  buildNextWorkspaceDraft,
  buildWorkspaceDraftFromSummary,
} from "@/features/model-center/workspaceRouting";
import type {
  TtsRegistryAdapterDefinition,
  TtsRegistryFamilyDefinition,
  TtsRegistryFieldSchema,
  TtsRegistryWorkspaceSummary,
} from "@/types/ttsRegistry";

const WORKSPACES_ENDPOINT = "/v1/tts-registry/workspaces";
const ADAPTERS_ENDPOINT = "/v1/tts-registry/adapters";
const DEFAULT_WORKSPACE_FORM_SCHEMA: TtsRegistryFieldSchema[] = [
  {
    field_key: "display_name",
    label: "工作区名称",
    scope: "workspace",
    visibility: "required",
    input_kind: "text",
    required: true,
  },
  {
    field_key: "slug",
    label: "工作区标识",
    scope: "workspace",
    visibility: "optional",
    input_kind: "text",
  },
];

const router = useRouter();

const loading = ref(false);
const workspaceDialogVisible = ref(false);
const workspaceDialogLoading = ref(false);
const deleteDialogVisible = ref(false);
const deleteDialogLoading = ref(false);
const workspaceDialogMode = ref<"create" | "edit">("create");
const adapters = ref<TtsRegistryAdapterDefinition[]>([]);
const workspaces = ref<TtsRegistryWorkspaceSummary[]>([]);
const familyOptionsByAdapter = ref<Record<string, TtsRegistryFamilyDefinition[]>>({});
const workspaceDialogModel = ref<Record<string, unknown>>({});
const selectedAdapterId = ref("");
const selectedFamilyId = ref("");
const activeWorkspace = ref<TtsRegistryWorkspaceSummary | null>(null);
const workspacePendingDelete = ref<TtsRegistryWorkspaceSummary | null>(null);

const isEditingWorkspace = computed(() => workspaceDialogMode.value === "edit");
const familyOptions = computed(() => familyOptionsByAdapter.value[selectedAdapterId.value] ?? []);
const selectedFamily = computed(() =>
  familyOptions.value.find((family) => family.family_id === selectedFamilyId.value) ?? null,
);
const workspaceDialogTitle = computed(() =>
  isEditingWorkspace.value ? "编辑模型工作区" : "添加模型工作区",
);
const workspaceDialogSchema = computed(() => {
  const familySchema = selectedFamily.value?.workspace_form_schema ?? [];
  return familySchema.length > 0 ? familySchema : DEFAULT_WORKSPACE_FORM_SCHEMA;
});

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

async function ensureAdapterFamilies(adapterId: string): Promise<TtsRegistryFamilyDefinition[]> {
  const cachedFamilies = familyOptionsByAdapter.value[adapterId];
  if (cachedFamilies) {
    return cachedFamilies;
  }
  const families = await fetchAdapterFamilies(adapterId);
  familyOptionsByAdapter.value = {
    ...familyOptionsByAdapter.value,
    [adapterId]: families,
  };
  return families;
}

async function selectWorkspaceAdapter(adapterId: string) {
  selectedAdapterId.value = adapterId;
  if (!adapterId.trim()) {
    selectedFamilyId.value = "";
    return;
  }
  const families = await ensureAdapterFamilies(adapterId);
  if (!families.some((family) => family.family_id === selectedFamilyId.value)) {
    selectedFamilyId.value = families[0]?.family_id ?? "";
  }
}

function openWorkspace(workspace: TtsRegistryWorkspaceSummary) {
  void router.push(buildModelWorkspaceRouteLocation(workspace));
}

async function openCreateWorkspaceDialog() {
  const firstAdapterId = adapters.value[0]?.adapter_id ?? "";
  if (!firstAdapterId) {
    ElMessage.warning("当前没有可用 adapter，无法创建模型工作区");
    return;
  }

  workspaceDialogMode.value = "create";
  activeWorkspace.value = null;
  workspaceDialogModel.value = buildNextWorkspaceDraft(workspaces.value);
  selectedFamilyId.value = "";
  await selectWorkspaceAdapter(firstAdapterId);
  workspaceDialogVisible.value = true;
}

async function openEditWorkspaceDialog(workspace: TtsRegistryWorkspaceSummary) {
  workspaceDialogMode.value = "edit";
  activeWorkspace.value = workspace;
  workspaceDialogModel.value = buildWorkspaceDraftFromSummary(workspace);
  selectedAdapterId.value = workspace.adapter_id;
  const families = await ensureAdapterFamilies(workspace.adapter_id);
  familyOptionsByAdapter.value = {
    ...familyOptionsByAdapter.value,
    [workspace.adapter_id]: families,
  };
  selectedFamilyId.value = workspace.family_id;
  workspaceDialogVisible.value = true;
}

function openDeleteWorkspaceDialog(workspace: TtsRegistryWorkspaceSummary) {
  workspacePendingDelete.value = workspace;
  deleteDialogVisible.value = true;
}

function closeWorkspaceDialog() {
  workspaceDialogVisible.value = false;
  workspaceDialogLoading.value = false;
}

function closeDeleteDialog() {
  deleteDialogVisible.value = false;
  deleteDialogLoading.value = false;
  workspacePendingDelete.value = null;
}

async function submitWorkspaceDialog(payload: Record<string, unknown>) {
  const displayName = typeof payload.display_name === "string" ? payload.display_name.trim() : "";
  const slug = typeof payload.slug === "string" ? payload.slug.trim() : "";
  if (!displayName || !slug) {
    ElMessage.warning("请先填写工作区名称和标识");
    return;
  }
  if (!selectedAdapterId.value.trim() || !selectedFamilyId.value.trim()) {
    ElMessage.warning("请先选择 adapter 和 family");
    return;
  }

  workspaceDialogLoading.value = true;
  try {
    if (workspaceDialogMode.value === "create") {
      const createdWorkspace = await createRegistryWorkspace({
        adapter_id: selectedAdapterId.value,
        family_id: selectedFamilyId.value,
        display_name: displayName,
        slug,
      });
      await loadModelHub();
      closeWorkspaceDialog();
      openWorkspace(createdWorkspace);
      return;
    }

    if (!activeWorkspace.value) {
      throw new Error("缺少待编辑的 workspace。");
    }

    await patchRegistryWorkspace(activeWorkspace.value.workspace_id, {
      display_name: displayName,
      slug,
    });
    await loadModelHub();
    closeWorkspaceDialog();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存模型工作区失败");
  } finally {
    workspaceDialogLoading.value = false;
  }
}

async function confirmDeleteWorkspace() {
  if (!workspacePendingDelete.value) {
    return;
  }

  deleteDialogLoading.value = true;
  try {
    await deleteRegistryWorkspace(workspacePendingDelete.value.workspace_id);
    await loadModelHub();
    closeDeleteDialog();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "删除模型工作区失败");
  } finally {
    deleteDialogLoading.value = false;
  }
}

onMounted(() => {
  void loadModelHub();
});
</script>

<template>
  <div class="mx-auto max-w-[1440px] px-8 py-8">
    <div class="mb-6 flex items-center justify-between gap-4">
      <div>
        <h1 class="text-2xl font-bold text-foreground">模型中心</h1>
        <p class="mt-1 text-sm text-muted-fg">
          当前工作区导航基于 {{ WORKSPACES_ENDPOINT }} 的摘要路由字段；adapter/family 元数据仍由 {{ ADAPTERS_ENDPOINT }} 提供。
        </p>
        <p class="mt-1 text-xs text-muted-fg">
          当前已发现 {{ adapters.length }} 个 adapter，{{ workspaces.length }} 个 workspace。
        </p>
      </div>
      <el-button type="primary" :loading="workspaceDialogLoading && !isEditingWorkspace" @click="openCreateWorkspaceDialog">
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
          <div class="flex items-center justify-between gap-4 px-3 py-3">
            <button
              class="min-w-0 flex-1 text-left"
              @click="openWorkspace(workspace)"
            >
              <div class="truncate text-sm font-medium text-foreground">{{ workspace.display_name }}</div>
              <div class="mt-1 text-xs text-muted-fg">
                {{ workspace.family_display_name }} / {{ workspace.slug }}
              </div>
            </button>
            <div class="flex shrink-0 items-center gap-2">
              <span class="text-xs text-muted-fg">{{ workspace.status }}</span>
              <el-button text size="small" @click.stop="openEditWorkspaceDialog(workspace)">编辑</el-button>
              <el-button text size="small" type="danger" @click.stop="openDeleteWorkspaceDialog(workspace)">
                删除
              </el-button>
            </div>
          </div>
        </li>
      </ul>
    </section>

    <WorkspaceDialog
      v-model:visible="workspaceDialogVisible"
      :title="workspaceDialogTitle"
      :schema="workspaceDialogSchema"
      :model-value="workspaceDialogModel"
      :loading="workspaceDialogLoading"
      :submit-text="isEditingWorkspace ? '保存修改' : '创建工作区'"
      :show-advanced="false"
      @submit="submitWorkspaceDialog"
      @cancel="closeWorkspaceDialog"
    >
      <template #before-form>
        <div class="grid gap-4 md:grid-cols-2">
          <div class="space-y-2">
            <div class="text-sm font-medium text-foreground">Adapter</div>
            <el-select
              :model-value="selectedAdapterId"
              :disabled="workspaceDialogLoading || isEditingWorkspace"
              class="w-full"
              placeholder="请选择 adapter"
              @update:model-value="selectWorkspaceAdapter(String($event ?? ''))"
            >
              <el-option
                v-for="adapter in adapters"
                :key="adapter.adapter_id"
                :label="adapter.display_name"
                :value="adapter.adapter_id"
              />
            </el-select>
          </div>
          <div class="space-y-2">
            <div class="text-sm font-medium text-foreground">Family</div>
            <el-select
              v-model="selectedFamilyId"
              :disabled="workspaceDialogLoading || isEditingWorkspace"
              class="w-full"
              placeholder="请选择 family"
            >
              <el-option
                v-for="family in familyOptions"
                :key="family.family_id"
                :label="family.display_name"
                :value="family.family_id"
              />
            </el-select>
          </div>
        </div>
      </template>
    </WorkspaceDialog>

    <DeleteConfirmDialog
      v-model:visible="deleteDialogVisible"
      title="删除模型工作区"
      :message="workspacePendingDelete ? `确定删除工作区「${workspacePendingDelete.display_name}」吗？` : '确定删除当前工作区吗？'"
      :loading="deleteDialogLoading"
      confirm-text="删除工作区"
      @submit="confirmDeleteWorkspace"
      @cancel="closeDeleteDialog"
    />
  </div>
</template>
