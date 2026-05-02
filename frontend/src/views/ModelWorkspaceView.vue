<script setup lang="ts">
import DeleteConfirmDialog from "@/components/model-center/DeleteConfirmDialog.vue";
import MainModelDialog from "@/components/model-center/MainModelDialog.vue";
import MainModelListPanel from "@/components/model-center/MainModelListPanel.vue";
import ModelWorkspaceHeader from "@/components/model-center/ModelWorkspaceHeader.vue";
import PresetDialog from "@/components/model-center/PresetDialog.vue";
import PresetListPanel from "@/components/model-center/PresetListPanel.vue";
import SecretEditorDialog from "@/components/model-center/SecretEditorDialog.vue";
import SubmodelDialog from "@/components/model-center/SubmodelDialog.vue";
import SubmodelListPanel from "@/components/model-center/SubmodelListPanel.vue";
import WorkspaceDialog from "@/components/model-center/WorkspaceDialog.vue";
import { useModelWorkspaceAdmin } from "@/composables/useModelWorkspaceAdmin";

const {
  loading,
  errorMessage,
  workspaceSummary,
  workspaceTree,
  familyDefinition,
  selectedMainModelId,
  selectedSubmodelId,
  workspaceDialogVisible,
  workspaceDialogLoading,
  workspaceDialogModel,
  workspaceDialogSchema,
  mainModelDialogVisible,
  mainModelDialogLoading,
  mainModelDialogMode,
  mainModelDialogModel,
  mainModelDialogSchema,
  submodelDialogVisible,
  submodelDialogLoading,
  submodelDialogMode,
  submodelDialogModel,
  submodelDialogSchema,
  presetDialogVisible,
  presetDialogLoading,
  presetDialogMode,
  presetDialogModel,
  presetDialogSchema,
  secretEditorDialogVisible,
  secretEditorDialogLoading,
  secretEditorModel,
  secretEditorFields,
  deleteDialogVisible,
  deleteDialogLoading,
  deleteDialogTitle,
  deleteDialogMessage,
  selectedMainModel,
  selectedSubmodel,
  selectedPresets,
  canCreateSubmodels,
  canCreatePresets,
  selectMainModel,
  selectSubmodel,
  openModelHub,
  openImportModelPackageDialog,
  openWorkspaceEditDialog,
  closeWorkspaceDialog,
  submitWorkspaceDialog,
  openMainModelCreateDialog,
  openMainModelEditDialog,
  closeMainModelDialog,
  submitMainModelDialog,
  openSubmodelCreateDialog,
  openSubmodelEditDialog,
  closeSubmodelDialog,
  submitSubmodelDialog,
  openPresetCreateDialog,
  openPresetEditDialog,
  closePresetDialog,
  submitPresetDialog,
  openSecretEditorDialog,
  closeSecretEditorDialog,
  submitSecretEditorDialog,
  runSubmodelConnectivityCheck,
  openDeleteWorkspaceDialog,
  openDeleteMainModelDialog,
  openDeleteSubmodelDialog,
  openDeletePresetDialog,
  closeDeleteDialog,
  confirmDeleteDialog,
} = useModelWorkspaceAdmin();
</script>

<template>
  <div class="mx-auto max-w-[1440px] px-8 py-8">
    <ModelWorkspaceHeader
      :workspace-summary="workspaceSummary"
      :family-definition="familyDefinition"
      @back="openModelHub"
      @import-model-package="openImportModelPackageDialog"
      @edit-workspace="openWorkspaceEditDialog"
      @delete-workspace="openDeleteWorkspaceDialog"
    />

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

    <div
      v-else-if="workspaceSummary && workspaceTree && familyDefinition"
      class="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]"
    >
      <MainModelListPanel
        :items="workspaceTree.main_models"
        :selected-main-model-id="selectedMainModelId"
        @select="selectMainModel"
        @create="openMainModelCreateDialog"
        @edit="openMainModelEditDialog"
        @delete="openDeleteMainModelDialog"
      />

      <div class="space-y-6">
        <SubmodelListPanel
          :items="selectedMainModel?.submodels ?? []"
          :selected-submodel-id="selectedSubmodelId"
          :allow-create="canCreateSubmodels"
          :allow-delete="canCreateSubmodels"
          @select="selectSubmodel"
          @create="openSubmodelCreateDialog"
          @edit="openSubmodelEditDialog"
          @delete="openDeleteSubmodelDialog"
          @edit-secrets="openSecretEditorDialog"
          @check-connectivity="runSubmodelConnectivityCheck"
        />

        <PresetListPanel
          :items="selectedPresets"
          :supports-presets="canCreatePresets"
          :allow-delete="canCreatePresets"
          @create="openPresetCreateDialog"
          @edit="openPresetEditDialog"
          @delete="openDeletePresetDialog"
        />

        <section
          v-if="selectedMainModel == null"
          class="rounded-card border border-border bg-card px-5 py-6 text-sm text-muted-fg shadow-card dark:border-transparent"
        >
          当前还没有可选主模型，右侧管理区暂为空状态。
        </section>

        <section
          v-else-if="selectedSubmodel == null && canCreateSubmodels"
          class="rounded-card border border-border bg-card px-5 py-6 text-sm text-muted-fg shadow-card dark:border-transparent"
        >
          当前主模型下没有子模型，预设区暂为空状态。
        </section>
      </div>
    </div>

    <WorkspaceDialog
      v-model:visible="workspaceDialogVisible"
      title="编辑工作区"
      :schema="workspaceDialogSchema"
      :model-value="workspaceDialogModel"
      :loading="workspaceDialogLoading"
      submit-text="保存工作区"
      :show-advanced="false"
      @submit="submitWorkspaceDialog"
      @cancel="closeWorkspaceDialog"
    />

    <MainModelDialog
      v-model:visible="mainModelDialogVisible"
      :title="mainModelDialogMode === 'create' ? '新增主模型' : '编辑主模型'"
      :schema="mainModelDialogSchema"
      :model-value="mainModelDialogModel"
      :loading="mainModelDialogLoading"
      submit-text="保存主模型"
      @submit="submitMainModelDialog"
      @cancel="closeMainModelDialog"
    />

    <SubmodelDialog
      v-model:visible="submodelDialogVisible"
      :title="submodelDialogMode === 'create' ? '新增子模型' : '编辑子模型'"
      :schema="submodelDialogSchema"
      :model-value="submodelDialogModel"
      :loading="submodelDialogLoading"
      submit-text="保存子模型"
      @submit="submitSubmodelDialog"
      @cancel="closeSubmodelDialog"
    />

    <PresetDialog
      v-model:visible="presetDialogVisible"
      :title="presetDialogMode === 'create' ? '新增预设' : '编辑预设'"
      :schema="presetDialogSchema"
      :model-value="presetDialogModel"
      :loading="presetDialogLoading"
      submit-text="保存预设"
      @submit="submitPresetDialog"
      @cancel="closePresetDialog"
    />

    <SecretEditorDialog
      v-model:visible="secretEditorDialogVisible"
      title="配置 Secrets"
      :fields="secretEditorFields"
      :model-value="secretEditorModel"
      :loading="secretEditorDialogLoading"
      submit-text="保存 Secrets"
      @submit="submitSecretEditorDialog"
      @cancel="closeSecretEditorDialog"
    />

    <DeleteConfirmDialog
      v-model:visible="deleteDialogVisible"
      :title="deleteDialogTitle"
      :message="deleteDialogMessage"
      :loading="deleteDialogLoading"
      @submit="confirmDeleteDialog"
      @cancel="closeDeleteDialog"
    />
  </div>
</template>
