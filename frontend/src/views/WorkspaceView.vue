<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick, h } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { useRoute, useRouter } from "vue-router";

import { useEditSession } from "@/composables/useEditSession";
import { useInputDraft, type InputTextLanguage } from "@/composables/useInputDraft";
import { useInferenceParamsCache } from "@/composables/useInferenceParamsCache";
import { buildInitializeRequest } from "@/api/editSessionContract";
import { uploadEditSessionReferenceAudio } from "@/api/editSession";
import { fetchBindingCatalog } from "@/api/ttsRegistry";
import WorkspaceEmptyState from "@/components/workspace/WorkspaceEmptyState.vue";
import WorkspaceFailedState from "@/components/workspace/WorkspaceFailedState.vue";
import WorkspaceInitForm from "@/components/workspace/WorkspaceInitForm.vue";
import ParameterPanelHost from "@/components/workspace/ParameterPanelHost.vue";
import WorkspaceEditorHost from "@/components/workspace/WorkspaceEditorHost.vue";
import MainActionButton from "@/components/workspace/MainActionButton.vue";
import WaveformStrip from "@/components/workspace/WaveformStrip.vue";
import TransportControlBar from "@/components/workspace/TransportControlBar.vue";
import RenderJobProgressBar from "@/components/workspace/RenderJobProgressBar.vue";
import {
  buildReferenceSelectionEntry,
  resolveReferenceSelectionBySource,
  resolveReferenceSelectionForBinding,
  upsertReferenceSelectionByBinding,
  type ReferenceSelectionByBinding,
} from "@/features/reference-binding";
import { useRuntimeState } from "@/composables/useRuntimeState";
import { resolveInitializeReferenceAudioPath } from "@/utils/referenceAudioSelection";
import { useParameterPanel } from "@/composables/useParameterPanel";
import { useWorkspaceDialogState } from "@/composables/useWorkspaceDialogState";
import ExportDialog from "@/components/workspace/ExportDialog.vue";
import ParameterDraftConfirm from "@/components/workspace/ParameterDraftConfirm.vue";
import { resolveWorkspaceEntryAction } from "@/components/workspace/sessionHandoff";
import { buildTextLanguageResolutionDialogModel } from "@/utils/textLanguageResolution";
import {
  flattenBindingCatalog,
  type RegistryBindingOption,
} from "@/types/ttsRegistry";
import type { BindingReference } from "@/types/editSession";

const route = useRoute();
const router = useRouter();
const {
  sessionStatus,
  discoverSession,
  initialize,
  clearSession,
  backfillInputDraftFromAppliedText,
  rememberSessionInitialText,
  sourceDraftRevision,
} = useEditSession();
const {
  text,
  textLanguage,
  draftRevision,
  lastSentToSessionRevision,
  source,
  setTextLanguage,
} = useInputDraft();
const { currentRenderJob } = useRuntimeState();
const parameterPanel = useParameterPanel();
const { exportDialogVisible, closeExportDialog } = useWorkspaceDialogState();
const bindings = ref<RegistryBindingOption[]>([]);
const hasAvailableBindings = computed(() => bindings.value.length > 0);
const selectedBinding = computed(() =>
  bindings.value.find((binding) => binding.bindingKey === initParams.value.binding_key) ?? null,
);
const workspaceEntryAction = computed(() =>
  resolveWorkspaceEntryAction({
    sessionStatus: sessionStatus.value,
    hasInputText: text.value.trim().length > 0,
    inputSource: source.value,
    draftRevision: draftRevision.value,
    lastSentToSessionRevision: lastSentToSessionRevision.value,
    sourceDraftRevision: sourceDraftRevision.value,
  }),
);
const handoffConfirmVisible = ref(false);
const promptedRebuildRevision = ref<number | null>(null);
let pendingGuardedAction: (() => Promise<void>) | null = null;

interface WorkspaceInitParams {
  binding_key: string;
  binding_ref: BindingReference | null;
  speed: number;
  temperature: number;
  top_p: number;
  top_k: number;
  noise_scale: number;
  pause_length: number;
  text_lang: string;
  text_split_method: string;
  ref_source: "preset" | "custom";
  custom_ref_file: File | null;
  custom_ref_path: string | null;
  ref_text: string;
  ref_lang: string;
  referenceSelectionsByBinding: ReferenceSelectionByBinding;
}

const initParams = ref<WorkspaceInitParams>({
  binding_key: "",
  binding_ref: null,
  speed: 1.0,
  temperature: 1.0,
  top_p: 1.0,
  top_k: 15,
  noise_scale: 0.35,
  pause_length: 0.3,
  text_lang: "auto",
  text_split_method: "cut5",
  ref_source: "preset",
  custom_ref_file: null,
  custom_ref_path: null,
  ref_text: "",
  ref_lang: "auto",
  referenceSelectionsByBinding: {},
});

const { restoreCache, persistCacheWhenIdle } = useInferenceParamsCache();
const isRestoring = ref(false);
const isBootstrappingWorkspace = ref(true);

function readNumericDefault(
  binding: RegistryBindingOption | null,
  key: "speed" | "temperature" | "top_p" | "top_k" | "noise_scale" | "pause_length",
  fallback: number,
): number {
  const value = binding?.defaults[key];
  return typeof value === "number" ? value : fallback;
}

function applyBindingDefaults(
  params: WorkspaceInitParams,
  binding: RegistryBindingOption | null,
): WorkspaceInitParams {
  if (!binding) {
    return params;
  }

  return {
    ...params,
    binding_key: binding.bindingKey,
    binding_ref: binding.bindingRef,
    speed: readNumericDefault(binding, "speed", params.speed),
    temperature: readNumericDefault(binding, "temperature", params.temperature),
    top_p: readNumericDefault(binding, "top_p", params.top_p),
    top_k: readNumericDefault(binding, "top_k", params.top_k),
    noise_scale: readNumericDefault(binding, "noise_scale", params.noise_scale),
    pause_length: readNumericDefault(binding, "pause_length", params.pause_length),
  };
}

function applyReferenceSelectionForBinding(
  params: WorkspaceInitParams,
  binding: RegistryBindingOption,
): WorkspaceInitParams {
  const { selection } = resolveReferenceSelectionForBinding({
    bindingRef: binding.bindingRef,
    bindingOptions: bindings.value,
    selections: params.referenceSelectionsByBinding,
  });

  return {
    ...params,
    binding_key: binding.bindingKey,
    binding_ref: binding.bindingRef,
    ref_source: selection.source,
    custom_ref_path: selection.custom_ref_path,
    ref_text: selection.ref_text,
    ref_lang: selection.ref_lang,
  };
}

function syncReferenceSelectionForCurrentBinding(
  params: WorkspaceInitParams,
): WorkspaceInitParams {
  if (!params.binding_ref) {
    return params;
  }

  return {
    ...params,
    referenceSelectionsByBinding: upsertReferenceSelectionByBinding({
      selections: params.referenceSelectionsByBinding,
      bindingRef: params.binding_ref,
      entry: buildReferenceSelectionEntry({
        source: params.ref_source,
        customRefPath: params.custom_ref_path,
        refText: params.ref_text,
        refLang: params.ref_lang,
      }),
    }),
  };
}

function buildCachePayload(): Record<string, unknown> {
  const syncedParams = syncReferenceSelectionForCurrentBinding({
    ...initParams.value,
    custom_ref_file: null,
  });

  return {
    binding_key: syncedParams.binding_key,
    binding_ref: syncedParams.binding_ref,
    speed: syncedParams.speed,
    temperature: syncedParams.temperature,
    top_p: syncedParams.top_p,
    top_k: syncedParams.top_k,
    noise_scale: syncedParams.noise_scale,
    pause_length: syncedParams.pause_length,
    text_lang: syncedParams.text_lang,
    text_split_method: syncedParams.text_split_method,
    referenceSelectionsByBinding: syncedParams.referenceSelectionsByBinding,
  };
}

watch(
  initParams,
  () => {
    if (isRestoring.value) {
      return;
    }
    persistCacheWhenIdle(buildCachePayload());
  },
  { deep: true },
);

watch(textLanguage, (nextLanguage) => {
  if (initParams.value.text_lang !== nextLanguage) {
    initParams.value.text_lang = nextLanguage;
  }
});

async function hydrateWorkspaceRoute() {
  try {
    const [, bindingCatalog] = await Promise.all([discoverSession(), fetchBindingCatalog()]);
    const loadedBindings = flattenBindingCatalog(bindingCatalog);
    bindings.value = loadedBindings;
    parameterPanel.setBindings(loadedBindings);
    if (loadedBindings.length === 0) {
      return;
    }

    isRestoring.value = true;
    const cached = await restoreCache();
    const payload = cached?.payload;

    const cachedBindingKey =
      payload && typeof payload.binding_key === "string"
        ? payload.binding_key
        : null;
    const initialBinding =
      (cachedBindingKey
        ? loadedBindings.find((binding) => binding.bindingKey === cachedBindingKey) ?? null
        : null)
      ?? loadedBindings[0]
      ?? null;

    if (!initialBinding) {
      return;
    }

    let nextParams: WorkspaceInitParams = {
      ...initParams.value,
      binding_key: initialBinding.bindingKey,
      binding_ref: initialBinding.bindingRef,
      referenceSelectionsByBinding:
        payload && typeof payload.referenceSelectionsByBinding === "object" && payload.referenceSelectionsByBinding
          ? (payload.referenceSelectionsByBinding as ReferenceSelectionByBinding)
          : {},
    };

    nextParams = applyBindingDefaults(nextParams, initialBinding);

    if (payload) {
      if (typeof payload.speed === "number") {
        nextParams.speed = payload.speed;
      }
      if (typeof payload.temperature === "number") {
        nextParams.temperature = payload.temperature;
      }
      if (typeof payload.top_p === "number") {
        nextParams.top_p = payload.top_p;
      }
      if (typeof payload.top_k === "number") {
        nextParams.top_k = payload.top_k;
      }
      if (typeof payload.noise_scale === "number") {
        nextParams.noise_scale = payload.noise_scale;
      }
      if (typeof payload.pause_length === "number") {
        nextParams.pause_length = payload.pause_length;
      }
      if (typeof payload.text_split_method === "string") {
        nextParams.text_split_method = payload.text_split_method;
      }
      if (typeof payload.text_lang === "string") {
        nextParams.text_lang = payload.text_lang;
      }
    }

    nextParams.text_lang = textLanguage.value;
    initParams.value = applyReferenceSelectionForBinding(nextParams, initialBinding);

    await nextTick();
    isRestoring.value = false;
  } catch (error) {
    isRestoring.value = false;
    console.error("Failed to fill init params", error);
  } finally {
    await nextTick();
    isBootstrappingWorkspace.value = false;
  }
}

function openModelHub() {
  void router.push("/models");
}

function handleInitParamsChange(nextParams: WorkspaceInitParams) {
  initParams.value = syncReferenceSelectionForCurrentBinding({
    ...nextParams,
    text_lang: textLanguage.value,
  });
}

async function handleRequestTextLanguageChange(nextLanguage: InputTextLanguage) {
  const currentLanguage = textLanguage.value;
  if (nextLanguage === currentLanguage) {
    return;
  }

  const dialogModel = buildTextLanguageResolutionDialogModel(currentLanguage, nextLanguage);

  try {
    await ElMessageBox.confirm(
      h("div", { class: "space-y-3 leading-6" }, [
        h("p", { class: "text-sm text-foreground" }, dialogModel.intro),
        h("div", { class: "rounded-md border border-border bg-muted/30 p-3" }, [
          h("p", { class: "text-xs font-semibold text-foreground" }, dialogModel.currentOption.actionLabel),
          h("p", { class: "mt-1 text-xs text-muted-fg" }, dialogModel.currentOption.description),
        ]),
        h("div", { class: "rounded-md border border-accent/30 bg-accent/5 p-3" }, [
          h("p", { class: "text-xs font-semibold text-foreground" }, dialogModel.nextOption.actionLabel),
          h("p", { class: "mt-1 text-xs text-muted-fg" }, dialogModel.nextOption.description),
        ]),
      ]),
      dialogModel.title,
      {
        confirmButtonText: dialogModel.nextOption.actionLabel,
        cancelButtonText: dialogModel.currentOption.actionLabel,
        distinguishCancelAndClose: true,
        closeOnClickModal: false,
        closeOnPressEscape: false,
        lockScroll: false,
      },
    );
  } catch {
    return;
  }

  setTextLanguage(nextLanguage);
}

onMounted(() => {
  void hydrateWorkspaceRoute();
});

onBeforeUnmount(() => {
  closeExportDialog();
});

watch(
  () => route.path,
  (path) => {
    if (path !== "/workspace") {
      closeExportDialog();
    }
  },
);

async function requestParameterDraftResolution(action: () => Promise<void>) {
  if (!parameterPanel.hasDirty.value) {
    await action();
    return;
  }

  pendingGuardedAction = action;
  handoffConfirmVisible.value = true;
}

function clearPendingGuardedAction() {
  pendingGuardedAction = null;
  handoffConfirmVisible.value = false;
}

async function runPendingGuardedAction() {
  const action = pendingGuardedAction;
  clearPendingGuardedAction();
  if (action) {
    await action();
  }
}

async function handleDiscardDraftAndContinue() {
  parameterPanel.discardDraft();
  await runPendingGuardedAction();
}

async function handleSubmitDraftAndContinue() {
  await parameterPanel.submitDraft();
  await runPendingGuardedAction();
}

const handleInit = async () => {
  if (!initParams.value.binding_ref || !text.value) {
    return;
  }
  if (sessionStatus.value === "ready") {
    try {
      await clearSession();
    } catch (error) {
      ElMessage.error(`清理旧会话失败: ${(error as Error).message}`);
      return;
    }
  }

  let customReferenceAudioPath: string | undefined;
  const effectiveReferenceSelection =
    initParams.value.ref_source === "preset"
      ? resolveReferenceSelectionBySource({
          bindingRef: initParams.value.binding_ref,
          source: "preset",
          bindingOptions: bindings.value,
          selections: initParams.value.referenceSelectionsByBinding,
        }).selection
      : buildReferenceSelectionEntry({
          source: "custom",
          customRefPath: initParams.value.custom_ref_path,
          refText: initParams.value.ref_text,
          refLang: initParams.value.ref_lang,
        });

  try {
    customReferenceAudioPath = await resolveInitializeReferenceAudioPath({
      refSource: effectiveReferenceSelection.source,
      presetReferenceAudioPath: selectedBinding.value?.referenceAudioPath ?? null,
      customReferenceAudioPath: effectiveReferenceSelection.custom_ref_path,
      customReferenceAudioFile: initParams.value.custom_ref_file,
      upload: uploadEditSessionReferenceAudio,
    });
  } catch (error) {
    ElMessage.error(`参考音频上传失败: ${(error as Error).message}`);
    return;
  }

  if (effectiveReferenceSelection.source === "custom") {
    initParams.value = syncReferenceSelectionForCurrentBinding({
      ...initParams.value,
      custom_ref_path: customReferenceAudioPath ?? null,
    });
  } else {
    initParams.value = syncReferenceSelectionForCurrentBinding({
      ...initParams.value,
      ref_source: effectiveReferenceSelection.source,
      custom_ref_path: effectiveReferenceSelection.custom_ref_path,
      ref_text: effectiveReferenceSelection.ref_text,
      ref_lang: effectiveReferenceSelection.ref_lang,
      custom_ref_file: null,
    });
  }

  const accepted = await initialize(
    buildInitializeRequest(
      {
        text: text.value,
        bindingRef: initParams.value.binding_ref,
        textLang: initParams.value.text_lang,
        speed: initParams.value.speed,
        temperature: initParams.value.temperature,
        topP: initParams.value.top_p,
        topK: initParams.value.top_k,
        noiseScale: initParams.value.noise_scale,
        pauseLength: initParams.value.pause_length,
        refSource: effectiveReferenceSelection.source,
        refText: effectiveReferenceSelection.ref_text,
        refLang: effectiveReferenceSelection.ref_lang,
        customRefFile: initParams.value.custom_ref_file,
        customRefPath: customReferenceAudioPath ?? null,
      },
      selectedBinding.value
        ? { refAudio: selectedBinding.value.referenceAudioPath }
        : undefined,
    ),
  );

  if (accepted) {
    rememberSessionInitialText(text.value);
    backfillInputDraftFromAppliedText(text.value);
  }
};

async function promptWorkspaceRebuild(currentRevision: number) {
  promptedRebuildRevision.value = currentRevision;

  await requestParameterDraftResolution(async () => {
    try {
      await ElMessageBox.confirm(
        "检测到文本输入页已有更新稿，是否用当前输入稿重建语音合成会话？",
        "用当前输入稿重建会话",
        {
          confirmButtonText: "重建会话",
          cancelButtonText: "暂不重建",
          type: "warning",
          closeOnClickModal: false,
          closeOnPressEscape: false,
          lockScroll: false,
        },
      );
    } catch {
      return;
    }

    await handleInit();
  });
}

const handleResetParams = () => {
  const binding = selectedBinding.value;
  if (!binding) {
    return;
  }

  initParams.value = syncReferenceSelectionForCurrentBinding({
    ...applyBindingDefaults(initParams.value, binding),
    ref_source: "preset",
    custom_ref_path: null,
    ref_text: binding.referenceText ?? "",
    ref_lang: binding.referenceLanguage ?? "auto",
    custom_ref_file: null,
  });
};

watch(
  () => ({
    action: workspaceEntryAction.value,
    status: sessionStatus.value,
    revision: draftRevision.value,
  }),
  async ({ action, status, revision }) => {
    if (isBootstrappingWorkspace.value) {
      return;
    }
    if (status !== "ready" || action !== "rebuild") {
      return;
    }
    if (promptedRebuildRevision.value === revision) {
      return;
    }

    await promptWorkspaceRebuild(revision);
  },
  { immediate: true },
);
</script>

<template>
  <div class="max-w-[1440px] mx-auto px-4 lg:px-8 py-6 h-[calc(100vh-3.5rem)] flex flex-col md:flex-row gap-6">
    <aside class="w-full md:w-[35%] lg:w-[30%] md:max-h-[calc(100vh-8rem)] md:overflow-y-auto space-y-5 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent pr-1">
      <div v-if="isBootstrappingWorkspace"></div>
      <ParameterPanelHost
        v-else-if="sessionStatus === 'ready' && hasAvailableBindings"
        :bindings="bindings"
      />
      <div
        v-else-if="!hasAvailableBindings"
        class="rounded-card border border-border bg-card px-5 py-6 space-y-3"
      >
        <p class="text-base font-semibold text-foreground">当前还没有可用模型</p>
        <p class="text-sm text-muted-fg">
          当前 workspace 已改为直接读取统一模型中心 binding catalog。请先前往模型管理配置至少一个可用 binding。
        </p>
        <el-button type="primary" @click="openModelHub">前往模型管理</el-button>
      </div>
      <WorkspaceInitForm
        v-else
        :model-value="initParams"
        :bindings="bindings"
        @update:model-value="handleInitParamsChange"
        @request-text-language-change="handleRequestTextLanguageChange"
        @reset="handleResetParams"
      />
    </aside>

    <main class="w-full md:w-[65%] lg:w-[70%] flex flex-col min-w-0 min-h-0 overflow-hidden relative">
      <div v-if="isBootstrappingWorkspace" class="h-full"></div>
      <WorkspaceEmptyState
        v-else-if="sessionStatus === 'empty'"
        :text="text"
        :can-submit="!!initParams.binding_ref && !!text"
        @submit="handleInit"
      />
      <WorkspaceFailedState v-else-if="sessionStatus === 'failed'" />

      <div v-else-if="sessionStatus === 'ready' || sessionStatus === 'initializing'" class="w-full h-full flex flex-col pt-2 gap-3">
        <WorkspaceEditorHost />
        <WaveformStrip />

        <div class="shrink-0 mb-4 flex items-center gap-3">
          <MainActionButton :session-status="sessionStatus" />

          <div class="flex-1 min-w-0 flex">
            <RenderJobProgressBar
              v-if="currentRenderJob && !['completed', 'failed', 'cancelled_partial'].includes(currentRenderJob.status)"
            />
            <TransportControlBar v-else />
          </div>
        </div>
      </div>
    </main>
  </div>

  <ExportDialog v-model:visible="exportDialogVisible" />
  <ParameterDraftConfirm
    :visible="handoffConfirmVisible"
    @cancel="clearPendingGuardedAction"
    @discard="handleDiscardDraftAndContinue"
    @submit="handleSubmitDraftAndContinue"
  />
</template>
