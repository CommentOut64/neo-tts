import { computed, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { useRoute, useRouter } from "vue-router";

import {
  checkRegistrySubmodelConnectivity,
  createRegistryMainModel,
  createRegistryPreset,
  createRegistrySubmodel,
  deleteRegistryMainModel,
  deleteRegistryPreset,
  deleteRegistrySubmodel,
  deleteRegistryWorkspace,
  fetchAdapterFamilies,
  fetchRegistryWorkspaceTree,
  fetchRegistryWorkspaces,
  importRegistryWorkspaceModelPackage,
  patchRegistryMainModel,
  patchRegistryPreset,
  patchRegistrySubmodel,
  patchRegistryWorkspace,
  putRegistrySubmodelSecrets,
} from "@/api/ttsRegistry";
import { buildSchemaFormModel } from "@/features/model-center/schemaForm";
import {
  buildModelWorkspaceRouteLocation,
  findWorkspaceSummaryByRoute,
} from "@/features/model-center/workspaceRouting";
import type {
  PatchRegistryMainModelPayload,
  PatchRegistryPresetPayload,
  PatchRegistrySubmodelPayload,
  PatchRegistryWorkspacePayload,
  PutRegistrySubmodelSecretsPayload,
  TtsRegistryFamilyDefinition,
  TtsRegistryFieldSchema,
  TtsRegistryMainModelNode,
  TtsRegistryPresetNode,
  TtsRegistrySubmodelNode,
  TtsRegistryWorkspaceSummary,
  TtsRegistryWorkspaceTree,
} from "@/types/ttsRegistry";

export interface WorkspaceSelectionState {
  selectedMainModelId: string | null;
  selectedSubmodelId: string | null;
}

interface DeleteTarget {
  scope: "workspace" | "mainModel" | "submodel" | "preset";
  label: string;
  mainModelId?: string;
  submodelId?: string;
  presetId?: string;
}

const DEFAULT_WORKSPACE_FIELDS: TtsRegistryFieldSchema[] = [
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

const DEFAULT_MAIN_MODEL_FIELDS: TtsRegistryFieldSchema[] = [
  {
    field_key: "display_name",
    label: "主模型名称",
    scope: "main_model",
    visibility: "required",
    input_kind: "text",
    required: true,
  },
];

const DEFAULT_SUBMODEL_FIELDS: TtsRegistryFieldSchema[] = [
  {
    field_key: "display_name",
    label: "子模型名称",
    scope: "submodel",
    visibility: "required",
    input_kind: "text",
    required: true,
  },
];

const DEFAULT_PRESET_FIELDS: TtsRegistryFieldSchema[] = [
  {
    field_key: "display_name",
    label: "预设名称",
    scope: "preset",
    visibility: "required",
    input_kind: "text",
    required: true,
  },
];

function mergeSchemaWithRequiredFields(
  schema: TtsRegistryFieldSchema[],
  requiredFields: TtsRegistryFieldSchema[],
): TtsRegistryFieldSchema[] {
  const existingKeys = new Set(schema.map((field) => field.field_key));
  return [
    ...requiredFields.filter((field) => !existingKeys.has(field.field_key)),
    ...schema,
  ];
}

function findMainModelIndex(tree: TtsRegistryWorkspaceTree, mainModelId: string | null): number {
  if (!mainModelId) {
    return -1;
  }
  return tree.main_models.findIndex((item) => item.main_model_id === mainModelId);
}

function findMainModel(tree: TtsRegistryWorkspaceTree, mainModelId: string | null): TtsRegistryMainModelNode | null {
  if (!mainModelId) {
    return null;
  }
  return tree.main_models.find((item) => item.main_model_id === mainModelId) ?? null;
}

function pickSubmodelFromMainModel(mainModel: TtsRegistryMainModelNode | null): string | null {
  return mainModel?.submodels[0]?.submodel_id ?? null;
}

function normalizeRegistryIdentifierSegment(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_")
    .replace(/[^a-z0-9_]/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "");
}

export function buildScopedRegistryIdentifier(input: {
  displayName: string;
  existingIds: string[];
  fallbackBaseId: string;
}): string {
  const normalizedBaseId = normalizeRegistryIdentifierSegment(input.displayName) || input.fallbackBaseId;
  const existingIds = new Set(input.existingIds);
  let candidateId = normalizedBaseId;
  let sequence = 2;
  while (existingIds.has(candidateId)) {
    candidateId = `${normalizedBaseId}_${sequence}`;
    sequence += 1;
  }
  return candidateId;
}

export function pickInitialWorkspaceSelection(tree: TtsRegistryWorkspaceTree): WorkspaceSelectionState {
  const firstMainModel = tree.main_models[0] ?? null;
  return {
    selectedMainModelId: firstMainModel?.main_model_id ?? null,
    selectedSubmodelId: pickSubmodelFromMainModel(firstMainModel),
  };
}

export function restoreWorkspaceSelection(
  previousTree: TtsRegistryWorkspaceTree | null,
  nextTree: TtsRegistryWorkspaceTree,
  currentSelection: WorkspaceSelectionState,
): WorkspaceSelectionState {
  const currentMainModel = findMainModel(nextTree, currentSelection.selectedMainModelId);
  if (currentMainModel) {
    const currentSubmodel =
      currentMainModel.submodels.find((item) => item.submodel_id === currentSelection.selectedSubmodelId) ?? null;
    return {
      selectedMainModelId: currentMainModel.main_model_id,
      selectedSubmodelId: currentSubmodel?.submodel_id ?? pickSubmodelFromMainModel(currentMainModel),
    };
  }

  if (!previousTree) {
    return pickInitialWorkspaceSelection(nextTree);
  }

  const previousMainModelIndex = findMainModelIndex(previousTree, currentSelection.selectedMainModelId);
  if (previousMainModelIndex === -1) {
    return pickInitialWorkspaceSelection(nextTree);
  }

  const fallbackMainModel =
    nextTree.main_models[previousMainModelIndex] ??
    nextTree.main_models[previousMainModelIndex - 1] ??
    nextTree.main_models[0] ??
    null;

  return {
    selectedMainModelId: fallbackMainModel?.main_model_id ?? null,
    selectedSubmodelId: pickSubmodelFromMainModel(fallbackMainModel),
  };
}

export function useModelWorkspaceAdmin() {
  const route = useRoute();
  const router = useRouter();

  const loading = ref(false);
  const errorMessage = ref("");
  const workspaceSummary = ref<TtsRegistryWorkspaceSummary | null>(null);
  const workspaceTree = ref<TtsRegistryWorkspaceTree | null>(null);
  const familyDefinition = ref<TtsRegistryFamilyDefinition | null>(null);
  const selectedMainModelId = ref<string | null>(null);
  const selectedSubmodelId = ref<string | null>(null);

  const workspaceDialogVisible = ref(false);
  const workspaceDialogLoading = ref(false);
  const workspaceDialogModel = ref<Record<string, unknown>>({});

  const mainModelDialogVisible = ref(false);
  const mainModelDialogLoading = ref(false);
  const mainModelDialogMode = ref<"create" | "edit">("create");
  const mainModelDialogModel = ref<Record<string, unknown>>({});
  const editingMainModelId = ref<string | null>(null);

  const submodelDialogVisible = ref(false);
  const submodelDialogLoading = ref(false);
  const submodelDialogMode = ref<"create" | "edit">("create");
  const submodelDialogModel = ref<Record<string, unknown>>({});
  const editingSubmodelId = ref<string | null>(null);

  const presetDialogVisible = ref(false);
  const presetDialogLoading = ref(false);
  const presetDialogMode = ref<"create" | "edit">("create");
  const presetDialogModel = ref<Record<string, unknown>>({});
  const editingPresetId = ref<string | null>(null);

  const secretEditorDialogVisible = ref(false);
  const secretEditorDialogLoading = ref(false);
  const secretEditorModel = ref<Record<string, string>>({});
  const secretEditorSubmodelId = ref<string | null>(null);

  const deleteDialogVisible = ref(false);
  const deleteDialogLoading = ref(false);
  const deleteTarget = ref<DeleteTarget | null>(null);

  const selectedMainModel = computed<TtsRegistryMainModelNode | null>(() => {
    if (!workspaceTree.value || !selectedMainModelId.value) {
      return null;
    }
    return workspaceTree.value.main_models.find((item) => item.main_model_id === selectedMainModelId.value) ?? null;
  });

  const selectedSubmodel = computed<TtsRegistrySubmodelNode | null>(() => {
    if (!selectedMainModel.value || !selectedSubmodelId.value) {
      return null;
    }
    return selectedMainModel.value.submodels.find((item) => item.submodel_id === selectedSubmodelId.value) ?? null;
  });

  const selectedPresets = computed(() => selectedSubmodel.value?.presets ?? []);
  const workspaceDialogSchema = computed(() =>
    mergeSchemaWithRequiredFields(familyDefinition.value?.workspace_form_schema ?? [], DEFAULT_WORKSPACE_FIELDS),
  );
  const mainModelDialogSchema = computed(() =>
    mergeSchemaWithRequiredFields(familyDefinition.value?.main_model_form_schema ?? [], DEFAULT_MAIN_MODEL_FIELDS),
  );
  const submodelDialogSchema = computed(() =>
    mergeSchemaWithRequiredFields(familyDefinition.value?.submodel_form_schema ?? [], DEFAULT_SUBMODEL_FIELDS),
  );
  const presetDialogSchema = computed(() =>
    mergeSchemaWithRequiredFields(familyDefinition.value?.preset_form_schema ?? [], DEFAULT_PRESET_FIELDS),
  );
  const secretEditorFields = computed(() =>
    (familyDefinition.value?.submodel_form_schema ?? [])
      .filter((field) => field.visibility === "hidden" && field.secret_name)
      .map((field) => ({
        key: field.secret_name as string,
        label: field.label,
        help_text: field.help_text,
      })),
  );
  const deleteDialogTitle = computed(() => {
    switch (deleteTarget.value?.scope) {
      case "mainModel":
        return "删除主模型";
      case "submodel":
        return "删除子模型";
      case "preset":
        return "删除预设";
      default:
        return "删除工作区";
    }
  });
  const deleteDialogMessage = computed(() => {
    if (!deleteTarget.value) {
      return "确认执行删除操作吗？";
    }
    return `确定删除「${deleteTarget.value.label}」吗？`;
  });
  const canCreateSubmodels = computed(() => familyDefinition.value?.supports_submodels ?? true);
  const canCreatePresets = computed(() => familyDefinition.value?.supports_presets ?? true);

  async function loadWorkspaceRouteContext(): Promise<TtsRegistryWorkspaceSummary | null> {
    const familyRoute = typeof route.params.familyRoute === "string" ? route.params.familyRoute : "";
    const workspaceSlug = typeof route.params.workspaceSlug === "string" ? route.params.workspaceSlug : "";
    if (!familyRoute.trim() || !workspaceSlug.trim()) {
      errorMessage.value = "模型工作区路由参数缺失，无法加载详情。";
      return null;
    }

    const summaries = await fetchRegistryWorkspaces();
    const matchedWorkspace = findWorkspaceSummaryByRoute(summaries, familyRoute, workspaceSlug);
    if (!matchedWorkspace) {
      errorMessage.value = `未找到模型工作区：${familyRoute}/${workspaceSlug}`;
      return null;
    }

    workspaceSummary.value = matchedWorkspace;
    return matchedWorkspace;
  }

  async function loadWorkspaceTree(workspaceId: string): Promise<TtsRegistryWorkspaceTree> {
    return fetchRegistryWorkspaceTree(workspaceId);
  }

  async function loadFamilyDefinition(
    adapterId: string,
    familyId: string,
  ): Promise<TtsRegistryFamilyDefinition> {
    const families = await fetchAdapterFamilies(adapterId);
    const matchedFamily = families.find((item) => item.family_id === familyId);
    if (!matchedFamily) {
      throw new Error(`未找到模型 family 定义：${familyId}`);
    }
    return matchedFamily;
  }

  function resolveSelectionFromPreference(nextTree: TtsRegistryWorkspaceTree, preferredSelection?: WorkspaceSelectionState | null) {
    if (!preferredSelection?.selectedMainModelId) {
      return null;
    }
    const preferredMainModel =
      nextTree.main_models.find((item) => item.main_model_id === preferredSelection.selectedMainModelId) ?? null;
    if (!preferredMainModel) {
      return null;
    }
    const preferredSubmodel =
      preferredMainModel.submodels.find((item) => item.submodel_id === preferredSelection.selectedSubmodelId) ?? null;
    return {
      selectedMainModelId: preferredMainModel.main_model_id,
      selectedSubmodelId: preferredSubmodel?.submodel_id ?? pickSubmodelFromMainModel(preferredMainModel),
    };
  }

  function applyWorkspaceTree(
    nextTree: TtsRegistryWorkspaceTree,
    preferredSelection?: WorkspaceSelectionState | null,
  ) {
    const preferred = resolveSelectionFromPreference(nextTree, preferredSelection);
    const nextSelection =
      preferred ??
      (workspaceTree.value == null
        ? pickInitialWorkspaceSelection(nextTree)
        : restoreWorkspaceSelection(workspaceTree.value, nextTree, {
            selectedMainModelId: selectedMainModelId.value,
            selectedSubmodelId: selectedSubmodelId.value,
          }));

    workspaceTree.value = nextTree;
    selectedMainModelId.value = nextSelection.selectedMainModelId;
    selectedSubmodelId.value = nextSelection.selectedSubmodelId;
  }

  async function refreshWorkspaceTree(preferredSelection?: WorkspaceSelectionState | null) {
    if (!workspaceSummary.value) {
      return;
    }
    const nextTree = await loadWorkspaceTree(workspaceSummary.value.workspace_id);
    applyWorkspaceTree(nextTree, preferredSelection);
  }

  async function reloadWorkspace() {
    loading.value = true;
    errorMessage.value = "";
    workspaceSummary.value = null;
    familyDefinition.value = null;

    try {
      const matchedWorkspace = await loadWorkspaceRouteContext();
      if (!matchedWorkspace) {
        workspaceTree.value = null;
        selectedMainModelId.value = null;
        selectedSubmodelId.value = null;
        return;
      }

      const [nextTree, nextFamilyDefinition] = await Promise.all([
        loadWorkspaceTree(matchedWorkspace.workspace_id),
        loadFamilyDefinition(matchedWorkspace.adapter_id, matchedWorkspace.family_id),
      ]);

      familyDefinition.value = nextFamilyDefinition;
      applyWorkspaceTree(nextTree);
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : "读取模型工作区失败";
      ElMessage.error(errorMessage.value);
    } finally {
      loading.value = false;
    }
  }

  async function syncWorkspaceSummaryRoute() {
    if (!workspaceSummary.value) {
      return;
    }
    const summaries = await fetchRegistryWorkspaces();
    const nextSummary = summaries.find((item) => item.workspace_id === workspaceSummary.value?.workspace_id) ?? null;
    if (!nextSummary) {
      throw new Error("更新后未找到当前 workspace 摘要。");
    }
    workspaceSummary.value = nextSummary;
    const currentFamilyRoute = typeof route.params.familyRoute === "string" ? route.params.familyRoute : "";
    const currentWorkspaceSlug = typeof route.params.workspaceSlug === "string" ? route.params.workspaceSlug : "";
    if (
      nextSummary.family_route_slug !== currentFamilyRoute ||
      nextSummary.slug !== currentWorkspaceSlug
    ) {
      await router.replace(buildModelWorkspaceRouteLocation(nextSummary));
    }
  }

  async function openImportModelPackageDialog() {
    if (!workspaceSummary.value || workspaceSummary.value.adapter_id !== "gpt_sovits_local") {
      return;
    }
    try {
      const { value } = await ElMessageBox.prompt("请输入 GPT-SoVITS 模型包目录或压缩包路径。", "导入模型包", {
        confirmButtonText: "开始导入",
        cancelButtonText: "取消",
        inputPlaceholder: "F:/models/demo-package",
      });
      const sourcePath = String(value ?? "").trim();
      if (!sourcePath) {
        return;
      }
      const imported = await importRegistryWorkspaceModelPackage(workspaceSummary.value.workspace_id, {
        source_path: sourcePath,
        storage_mode: "managed",
      });
      await refreshWorkspaceTree({
        selectedMainModelId: imported.main_model.main_model_id,
        selectedSubmodelId: imported.submodels[0]?.submodel_id ?? null,
      });
      ElMessage.success(`模型包已导入：${imported.main_model.display_name}`);
    } catch (error) {
      if (error === "cancel" || error === "close") {
        return;
      }
      const message = error instanceof Error ? error.message : "导入模型包失败";
      ElMessage.error(message);
    }
  }

  function selectMainModel(mainModelId: string) {
    selectedMainModelId.value = mainModelId;
    const nextMainModel = workspaceTree.value?.main_models.find((item) => item.main_model_id === mainModelId) ?? null;
    selectedSubmodelId.value = pickSubmodelFromMainModel(nextMainModel);
  }

  function selectSubmodel(submodelId: string) {
    selectedSubmodelId.value = submodelId;
  }

  function openModelHub() {
    void router.push("/models");
  }

  function openWorkspaceEditDialog() {
    if (!workspaceSummary.value) {
      return;
    }
    workspaceDialogModel.value = buildSchemaFormModel(workspaceDialogSchema.value, {
      display_name: workspaceSummary.value.display_name,
      slug: workspaceSummary.value.slug,
    });
    workspaceDialogVisible.value = true;
  }

  function closeWorkspaceDialog() {
    workspaceDialogVisible.value = false;
    workspaceDialogLoading.value = false;
  }

  async function submitWorkspaceDialog(payload: Record<string, unknown>) {
    if (!workspaceSummary.value) {
      return;
    }
    const display_name = typeof payload.display_name === "string" ? payload.display_name.trim() : "";
    const slug = typeof payload.slug === "string" ? payload.slug.trim() : "";
    if (!display_name || !slug) {
      ElMessage.warning("请先填写工作区名称和标识");
      return;
    }

    workspaceDialogLoading.value = true;
    try {
      const patchPayload: PatchRegistryWorkspacePayload = { display_name, slug };
      await patchRegistryWorkspace(workspaceSummary.value.workspace_id, patchPayload);
      await syncWorkspaceSummaryRoute();
      await reloadWorkspace();
      closeWorkspaceDialog();
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : "保存工作区失败");
    } finally {
      workspaceDialogLoading.value = false;
    }
  }

  function openMainModelCreateDialog() {
    mainModelDialogMode.value = "create";
    editingMainModelId.value = null;
    mainModelDialogModel.value = buildSchemaFormModel(mainModelDialogSchema.value, {});
    mainModelDialogVisible.value = true;
  }

  function openMainModelEditDialog(mainModelId: string) {
    const targetMainModel = workspaceTree.value?.main_models.find((item) => item.main_model_id === mainModelId) ?? null;
    if (!targetMainModel) {
      return;
    }
    mainModelDialogMode.value = "edit";
    editingMainModelId.value = mainModelId;
    mainModelDialogModel.value = buildSchemaFormModel(mainModelDialogSchema.value, {
      display_name: targetMainModel.display_name,
      status: targetMainModel.status,
      main_model_metadata: targetMainModel.main_model_metadata,
      default_submodel_id: targetMainModel.default_submodel_id,
    });
    mainModelDialogVisible.value = true;
  }

  function closeMainModelDialog() {
    mainModelDialogVisible.value = false;
    mainModelDialogLoading.value = false;
  }

  async function submitMainModelDialog(payload: Record<string, unknown>) {
    if (!workspaceSummary.value) {
      return;
    }
    const display_name = typeof payload.display_name === "string" ? payload.display_name.trim() : "";
    if (!display_name) {
      ElMessage.warning("请先填写主模型名称");
      return;
    }

    mainModelDialogLoading.value = true;
    try {
      if (mainModelDialogMode.value === "create") {
        const created = await createRegistryMainModel(workspaceSummary.value.workspace_id, {
          main_model_id: buildScopedRegistryIdentifier({
            displayName: display_name,
            existingIds: workspaceTree.value?.main_models.map((item) => item.main_model_id) ?? [],
            fallbackBaseId: "main_model",
          }),
          display_name,
          main_model_metadata:
            typeof payload.main_model_metadata === "object" && payload.main_model_metadata !== null
              ? (payload.main_model_metadata as Record<string, unknown>)
              : {},
        });
        await refreshWorkspaceTree({
          selectedMainModelId: created.main_model_id,
          selectedSubmodelId: null,
        });
      } else if (editingMainModelId.value) {
        const patchPayload: PatchRegistryMainModelPayload = {
          display_name,
          default_submodel_id:
            typeof payload.default_submodel_id === "string" ? payload.default_submodel_id : null,
        };
        if (typeof payload.main_model_metadata === "object" && payload.main_model_metadata !== null) {
          patchPayload.main_model_metadata = payload.main_model_metadata as Record<string, unknown>;
        }
        await patchRegistryMainModel(
          workspaceSummary.value.workspace_id,
          editingMainModelId.value,
          patchPayload,
        );
        await refreshWorkspaceTree({
          selectedMainModelId: editingMainModelId.value,
          selectedSubmodelId: selectedSubmodelId.value,
        });
      }
      closeMainModelDialog();
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : "保存主模型失败");
    } finally {
      mainModelDialogLoading.value = false;
    }
  }

  function openSubmodelCreateDialog() {
    if (!selectedMainModel.value) {
      ElMessage.warning("请先选择主模型");
      return;
    }
    if (!canCreateSubmodels.value) {
      ElMessage.warning("当前 family 不支持新增子模型");
      return;
    }
    submodelDialogMode.value = "create";
    editingSubmodelId.value = null;
    submodelDialogModel.value = buildSchemaFormModel(submodelDialogSchema.value, {});
    submodelDialogVisible.value = true;
  }

  function openSubmodelEditDialog(submodelId: string) {
    const targetSubmodel =
      selectedMainModel.value?.submodels.find((item) => item.submodel_id === submodelId) ?? null;
    if (!targetSubmodel) {
      return;
    }
    submodelDialogMode.value = "edit";
    editingSubmodelId.value = submodelId;
    submodelDialogModel.value = buildSchemaFormModel(submodelDialogSchema.value, {
      display_name: targetSubmodel.display_name,
      status: targetSubmodel.status,
      instance_assets: targetSubmodel.instance_assets,
      endpoint: targetSubmodel.endpoint,
      account_binding: targetSubmodel.account_binding,
      adapter_options: targetSubmodel.adapter_options,
      runtime_profile: targetSubmodel.runtime_profile,
    });
    submodelDialogVisible.value = true;
  }

  function closeSubmodelDialog() {
    submodelDialogVisible.value = false;
    submodelDialogLoading.value = false;
  }

  async function submitSubmodelDialog(payload: Record<string, unknown>) {
    if (!workspaceSummary.value || !selectedMainModel.value) {
      return;
    }
    const display_name = typeof payload.display_name === "string" ? payload.display_name.trim() : "";
    if (!display_name) {
      ElMessage.warning("请先填写子模型名称");
      return;
    }

    submodelDialogLoading.value = true;
    try {
      if (submodelDialogMode.value === "create") {
        const created = await createRegistrySubmodel(
          workspaceSummary.value.workspace_id,
          selectedMainModel.value.main_model_id,
          {
            submodel_id: buildScopedRegistryIdentifier({
              displayName: display_name,
              existingIds: selectedMainModel.value.submodels.map((item) => item.submodel_id),
              fallbackBaseId: "submodel",
            }),
            display_name,
            endpoint:
              typeof payload.endpoint === "object" && payload.endpoint !== null
                ? (payload.endpoint as Record<string, unknown>)
                : null,
            account_binding:
              typeof payload.account_binding === "object" && payload.account_binding !== null
                ? (payload.account_binding as Record<string, unknown>)
                : null,
            instance_assets:
              typeof payload.instance_assets === "object" && payload.instance_assets !== null
                ? (payload.instance_assets as Record<string, unknown>)
                : {},
            adapter_options:
              typeof payload.adapter_options === "object" && payload.adapter_options !== null
                ? (payload.adapter_options as Record<string, unknown>)
                : {},
            runtime_profile:
              typeof payload.runtime_profile === "object" && payload.runtime_profile !== null
                ? (payload.runtime_profile as Record<string, unknown>)
                : {},
          },
        );
        await refreshWorkspaceTree({
          selectedMainModelId: selectedMainModel.value.main_model_id,
          selectedSubmodelId: created.submodel_id,
        });
      } else if (editingSubmodelId.value) {
        const patchPayload: PatchRegistrySubmodelPayload = {
          display_name,
        };
        if (typeof payload.endpoint === "object" && payload.endpoint !== null) {
          patchPayload.endpoint = payload.endpoint as Record<string, unknown>;
        }
        if (typeof payload.account_binding === "object" && payload.account_binding !== null) {
          patchPayload.account_binding = payload.account_binding as Record<string, unknown>;
        }
        if (typeof payload.instance_assets === "object" && payload.instance_assets !== null) {
          patchPayload.instance_assets = payload.instance_assets as Record<string, unknown>;
        }
        if (typeof payload.adapter_options === "object" && payload.adapter_options !== null) {
          patchPayload.adapter_options = payload.adapter_options as Record<string, unknown>;
        }
        if (typeof payload.runtime_profile === "object" && payload.runtime_profile !== null) {
          patchPayload.runtime_profile = payload.runtime_profile as Record<string, unknown>;
        }
        await patchRegistrySubmodel(
          workspaceSummary.value.workspace_id,
          selectedMainModel.value.main_model_id,
          editingSubmodelId.value,
          patchPayload,
        );
        await refreshWorkspaceTree({
          selectedMainModelId: selectedMainModel.value.main_model_id,
          selectedSubmodelId: editingSubmodelId.value,
        });
      }
      closeSubmodelDialog();
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : "保存子模型失败");
    } finally {
      submodelDialogLoading.value = false;
    }
  }

  function openPresetCreateDialog() {
    if (!selectedSubmodel.value || !familyDefinition.value?.supports_presets) {
      ElMessage.warning("当前 family 不支持新增预设");
      return;
    }
    presetDialogMode.value = "create";
    editingPresetId.value = null;
    presetDialogModel.value = buildSchemaFormModel(presetDialogSchema.value, {});
    presetDialogVisible.value = true;
  }

  function openPresetEditDialog(presetId: string) {
    const targetPreset = selectedSubmodel.value?.presets.find((item) => item.preset_id === presetId) ?? null;
    if (!targetPreset) {
      return;
    }
    presetDialogMode.value = "edit";
    editingPresetId.value = presetId;
    presetDialogModel.value = buildSchemaFormModel(presetDialogSchema.value, {
      display_name: targetPreset.display_name,
      status: targetPreset.status,
      defaults: targetPreset.defaults,
      fixed_fields: targetPreset.fixed_fields,
      preset_assets: targetPreset.preset_assets,
    });
    presetDialogVisible.value = true;
  }

  function closePresetDialog() {
    presetDialogVisible.value = false;
    presetDialogLoading.value = false;
  }

  async function submitPresetDialog(payload: Record<string, unknown>) {
    if (!workspaceSummary.value || !selectedMainModel.value || !selectedSubmodel.value) {
      return;
    }
    const display_name = typeof payload.display_name === "string" ? payload.display_name.trim() : "";
    if (!display_name) {
      ElMessage.warning("请先填写预设名称");
      return;
    }

    presetDialogLoading.value = true;
    try {
      if (presetDialogMode.value === "create") {
        await createRegistryPreset(
          workspaceSummary.value.workspace_id,
          selectedMainModel.value.main_model_id,
          selectedSubmodel.value.submodel_id,
          {
            preset_id: buildScopedRegistryIdentifier({
              displayName: display_name,
              existingIds: selectedSubmodel.value.presets.map((item) => item.preset_id),
              fallbackBaseId: "preset",
            }),
            display_name,
            defaults:
              typeof payload.defaults === "object" && payload.defaults !== null
                ? (payload.defaults as Record<string, unknown>)
                : {},
            fixed_fields:
              typeof payload.fixed_fields === "object" && payload.fixed_fields !== null
                ? (payload.fixed_fields as Record<string, unknown>)
                : {},
            preset_assets:
              typeof payload.preset_assets === "object" && payload.preset_assets !== null
                ? (payload.preset_assets as Record<string, unknown>)
                : {},
          },
        );
      } else if (editingPresetId.value) {
        const patchPayload: PatchRegistryPresetPayload = {
          display_name,
        };
        if (typeof payload.defaults === "object" && payload.defaults !== null) {
          patchPayload.defaults = payload.defaults as Record<string, unknown>;
        }
        if (typeof payload.fixed_fields === "object" && payload.fixed_fields !== null) {
          patchPayload.fixed_fields = payload.fixed_fields as Record<string, unknown>;
        }
        if (typeof payload.preset_assets === "object" && payload.preset_assets !== null) {
          patchPayload.preset_assets = payload.preset_assets as Record<string, unknown>;
        }
        await patchRegistryPreset(
          workspaceSummary.value.workspace_id,
          selectedMainModel.value.main_model_id,
          selectedSubmodel.value.submodel_id,
          editingPresetId.value,
          patchPayload,
        );
      }
      await refreshWorkspaceTree({
        selectedMainModelId: selectedMainModel.value.main_model_id,
        selectedSubmodelId: selectedSubmodel.value.submodel_id,
      });
      closePresetDialog();
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : "保存预设失败");
    } finally {
      presetDialogLoading.value = false;
    }
  }

  function openSecretEditorDialog(submodelId: string) {
    secretEditorSubmodelId.value = submodelId;
    secretEditorModel.value = Object.fromEntries(secretEditorFields.value.map((field) => [field.key, ""]));
    secretEditorDialogVisible.value = true;
  }

  function closeSecretEditorDialog() {
    secretEditorDialogVisible.value = false;
    secretEditorDialogLoading.value = false;
  }

  async function submitSecretEditorDialog(payload: Record<string, string>) {
    if (!workspaceSummary.value || !selectedMainModel.value || !secretEditorSubmodelId.value) {
      return;
    }
    secretEditorDialogLoading.value = true;
    try {
      const normalizedPayload: PutRegistrySubmodelSecretsPayload = {
        secrets: Object.fromEntries(
          Object.entries(payload).filter(([, value]) => value.trim().length > 0),
        ),
      };
      await putRegistrySubmodelSecrets(
        workspaceSummary.value.workspace_id,
        selectedMainModel.value.main_model_id,
        secretEditorSubmodelId.value,
        normalizedPayload,
      );
      await refreshWorkspaceTree({
        selectedMainModelId: selectedMainModel.value.main_model_id,
        selectedSubmodelId: secretEditorSubmodelId.value,
      });
      closeSecretEditorDialog();
      ElMessage.success("Secrets 已更新");
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : "更新 secrets 失败");
    } finally {
      secretEditorDialogLoading.value = false;
    }
  }

  async function runSubmodelConnectivityCheck(submodelId: string) {
    if (!workspaceSummary.value || !selectedMainModel.value) {
      return;
    }
    try {
      const result = await checkRegistrySubmodelConnectivity(
        workspaceSummary.value.workspace_id,
        selectedMainModel.value.main_model_id,
        submodelId,
      );
      ElMessage.success(`联通性检查结果：${result.status}`);
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : "联通性检查失败");
    }
  }

  function openDeleteWorkspaceDialog() {
    if (!workspaceSummary.value) {
      return;
    }
    deleteTarget.value = {
      scope: "workspace",
      label: workspaceSummary.value.display_name,
    };
    deleteDialogVisible.value = true;
  }

  function openDeleteMainModelDialog(mainModelId: string) {
    const targetMainModel = workspaceTree.value?.main_models.find((item) => item.main_model_id === mainModelId) ?? null;
    if (!targetMainModel) {
      return;
    }
    deleteTarget.value = {
      scope: "mainModel",
      label: targetMainModel.display_name,
      mainModelId,
    };
    deleteDialogVisible.value = true;
  }

  function openDeleteSubmodelDialog(submodelId: string) {
    if (!familyDefinition.value?.supports_submodels) {
      return;
    }
    const targetSubmodel = selectedMainModel.value?.submodels.find((item) => item.submodel_id === submodelId) ?? null;
    if (!targetSubmodel) {
      return;
    }
    deleteTarget.value = {
      scope: "submodel",
      label: targetSubmodel.display_name,
      mainModelId: selectedMainModel.value?.main_model_id,
      submodelId,
    };
    deleteDialogVisible.value = true;
  }

  function openDeletePresetDialog(presetId: string) {
    if (!familyDefinition.value?.supports_presets) {
      return;
    }
    const targetPreset = selectedSubmodel.value?.presets.find((item) => item.preset_id === presetId) ?? null;
    if (!targetPreset) {
      return;
    }
    deleteTarget.value = {
      scope: "preset",
      label: targetPreset.display_name,
      mainModelId: selectedMainModel.value?.main_model_id,
      submodelId: selectedSubmodel.value?.submodel_id,
      presetId,
    };
    deleteDialogVisible.value = true;
  }

  function closeDeleteDialog() {
    deleteDialogVisible.value = false;
    deleteDialogLoading.value = false;
    deleteTarget.value = null;
  }

  async function confirmDeleteDialog() {
    if (!workspaceSummary.value || !deleteTarget.value) {
      return;
    }
    deleteDialogLoading.value = true;
    try {
      switch (deleteTarget.value.scope) {
        case "workspace":
          await deleteRegistryWorkspace(workspaceSummary.value.workspace_id);
          closeDeleteDialog();
          openModelHub();
          return;
        case "mainModel":
          if (!deleteTarget.value.mainModelId) {
            break;
          }
          await deleteRegistryMainModel(
            workspaceSummary.value.workspace_id,
            deleteTarget.value.mainModelId,
          );
          await refreshWorkspaceTree();
          break;
        case "submodel":
          if (!deleteTarget.value.mainModelId || !deleteTarget.value.submodelId) {
            break;
          }
          await deleteRegistrySubmodel(
            workspaceSummary.value.workspace_id,
            deleteTarget.value.mainModelId,
            deleteTarget.value.submodelId,
          );
          await refreshWorkspaceTree();
          break;
        case "preset":
          if (
            !deleteTarget.value.mainModelId ||
            !deleteTarget.value.submodelId ||
            !deleteTarget.value.presetId
          ) {
            break;
          }
          await deleteRegistryPreset(
            workspaceSummary.value.workspace_id,
            deleteTarget.value.mainModelId,
            deleteTarget.value.submodelId,
            deleteTarget.value.presetId,
          );
          await refreshWorkspaceTree({
            selectedMainModelId: deleteTarget.value.mainModelId,
            selectedSubmodelId: deleteTarget.value.submodelId,
          });
          break;
      }
      closeDeleteDialog();
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : "删除失败");
    } finally {
      deleteDialogLoading.value = false;
    }
  }

  watch(
    () => [route.params.familyRoute, route.params.workspaceSlug],
    () => {
      void reloadWorkspace();
    },
    { immediate: true },
  );

  return {
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
    loadWorkspaceRouteContext,
    loadWorkspaceTree,
    loadFamilyDefinition,
    refreshWorkspaceTree,
    reloadWorkspace,
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
  };
}
