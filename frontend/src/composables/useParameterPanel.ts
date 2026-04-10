import { computed, ref, watch } from "vue";
import { ElMessage } from "element-plus";

import {
  commitSegmentRenderProfile,
  commitSegmentRenderProfileBatch,
  commitSegmentVoiceBinding,
  commitSegmentVoiceBindingBatch,
  commitSessionRenderProfile,
  commitSessionVoiceBinding,
  updateEdge,
} from "@/api/editSession";
import { shouldBlockEdgeEditing } from "@/components/workspace/workspace-editor/workspaceEditorHostModel";
import { useEditSession } from "@/composables/useEditSession";
import { useRuntimeState } from "@/composables/useRuntimeState";
import { useWorkspaceLightEdit } from "@/composables/useWorkspaceLightEdit";
import { useWorkspaceProcessing } from "@/composables/useWorkspaceProcessing";
import {
  useSegmentSelection,
  type SelectionSnapshot,
} from "@/composables/useSegmentSelection";
import type {
  EdgeUpdateBody,
  RenderProfilePatch,
  VoiceBindingPatch,
} from "@/types/editSession";
import {
  resolveEffectiveParameters,
  type ResolvedParameterPanelValues,
} from "@/components/workspace/parameter-panel/resolveEffectiveParameters";
import {
  resolveParameterScope,
  type ParameterPanelScopeContext,
} from "@/components/workspace/parameter-panel/resolveParameterScope";
import { createParameterPatchQueue } from "@/components/workspace/parameter-panel/submitParameterPatchQueue";

const scopeContext = ref<ParameterPanelScopeContext>({
  scope: "session",
  segmentIds: [],
  edgeId: null,
});
const draftPatch = ref<{
  renderProfile: RenderProfilePatch;
  voiceBinding: VoiceBindingPatch;
  edge: EdgeUpdateBody;
}>({
  renderProfile: {},
  voiceBinding: {},
  edge: {},
});
const dirtyFieldSet = ref<Set<string>>(new Set());
const isSubmitting = ref(false);
const pendingScopeContext = ref<ParameterPanelScopeContext | null>(null);
const pendingSelectionSnapshot = ref<SelectionSnapshot | null>(null);
const confirmVisible = ref(false);
const flashPulse = ref(0);
const acceptedSelectionSnapshot = ref<SelectionSnapshot>({
  selectedSegmentIds: [],
  primarySelectedSegmentId: null,
  selectedEdgeId: null,
});
const lastStableScopeKey = ref<string | null>(null);
const lastStableResolvedValues = ref<ResolvedParameterPanelValues | null>(null);

type ParameterPanelResolvedStatus = "ready" | "resolving" | "unresolved";

function cloneScopeContext(context: ParameterPanelScopeContext): ParameterPanelScopeContext {
  return {
    scope: context.scope,
    segmentIds: [...context.segmentIds],
    edgeId: context.edgeId,
  };
}

function isSameScope(
  left: ParameterPanelScopeContext,
  right: ParameterPanelScopeContext,
): boolean {
  return (
    left.scope === right.scope &&
    left.edgeId === right.edgeId &&
    left.segmentIds.length === right.segmentIds.length &&
    left.segmentIds.every((segmentId, index) => segmentId === right.segmentIds[index])
  );
}

function clearDraftState() {
  draftPatch.value = {
    renderProfile: {},
    voiceBinding: {},
    edge: {},
  };
  dirtyFieldSet.value = new Set();
}

function buildScopeKey(context: ParameterPanelScopeContext): string {
  if (context.scope === "edge") {
    return `edge:${context.edgeId ?? ""}`;
  }

  return `${context.scope}:${context.segmentIds.join(",")}`;
}

function buildEmptyResolvedValues(): ResolvedParameterPanelValues {
  return {
    renderProfile: {
      speed: null,
      top_k: null,
      top_p: null,
      temperature: null,
      noise_scale: null,
      reference_audio_path: null,
      reference_text: null,
      reference_language: null,
    },
    voiceBinding: {
      voice_id: null,
      model_key: null,
      gpt_path: null,
      sovits_path: null,
    },
    edge: null,
  };
}

function cloneResolvedValues(values: ResolvedParameterPanelValues): ResolvedParameterPanelValues {
  return {
    renderProfile: {
      ...values.renderProfile,
    },
    voiceBinding: {
      ...values.voiceBinding,
    },
    edge: values.edge
      ? {
          ...values.edge,
        }
      : null,
  };
}

function hasResolvedValues(
  context: ParameterPanelScopeContext,
  values: ResolvedParameterPanelValues,
): boolean {
  if (context.scope === "edge") {
    return values.edge !== null;
  }

  return (
    values.renderProfile.speed !== null &&
    values.renderProfile.top_k !== null &&
    values.renderProfile.top_p !== null &&
    values.renderProfile.temperature !== null &&
    values.renderProfile.noise_scale !== null &&
    values.voiceBinding.voice_id !== null &&
    values.voiceBinding.model_key !== null
  );
}

export function useParameterPanel() {
  const editSession = useEditSession();
  const runtimeState = useRuntimeState();
  const lightEdit = useWorkspaceLightEdit();
  const workspaceProcessing = useWorkspaceProcessing();
  const selection = useSegmentSelection();
  const queue = createParameterPatchQueue();

  const desiredScopeContext = computed(() =>
    resolveParameterScope({
      selectedSegmentIds: selection.selectedSegmentIds.value,
      selectedEdgeId: selection.selectedEdgeId.value,
    }),
  );

  const dirtyFields = computed(() => Array.from(dirtyFieldSet.value));
  const dirtyFieldSetReadonly = computed(() => new Set(dirtyFieldSet.value));
  const hasDirty = computed(() => dirtyFieldSet.value.size > 0);
  const scopeKey = computed(() => buildScopeKey(scopeContext.value));
  const dirtyEdgeIds = computed(() => {
    if (
      scopeContext.value.scope !== "edge" ||
      !scopeContext.value.edgeId ||
      Object.keys(draftPatch.value.edge).length === 0
    ) {
      return new Set<string>();
    }

    return new Set([scopeContext.value.edgeId]);
  });

  const rawResolvedValues = computed<ResolvedParameterPanelValues>(() =>
    resolveEffectiveParameters({
      scope: scopeContext.value.scope,
      segmentIds: scopeContext.value.segmentIds,
      edgeId: scopeContext.value.edgeId,
      snapshot: editSession.snapshot.value,
      segments: editSession.segments.value,
      groups: editSession.groups.value,
      timeline: editSession.timeline.value,
      renderProfiles: editSession.renderProfiles.value,
      voiceBindings: editSession.voiceBindings.value,
      edges: editSession.edges.value,
    }),
  );

  const resolvedStatus = computed<ParameterPanelResolvedStatus>(() => {
    if (editSession.sessionStatus.value !== "ready") {
      return "unresolved";
    }

    if (editSession.formalStateStatus.value === "refreshing") {
      return "resolving";
    }

    if (editSession.formalStateStatus.value === "error") {
      return "unresolved";
    }

    return hasResolvedValues(scopeContext.value, rawResolvedValues.value)
      ? "ready"
      : "unresolved";
  });

  watch(
    [scopeKey, resolvedStatus, rawResolvedValues],
    ([nextScopeKey, nextResolvedStatus, nextResolvedValues]) => {
      if (nextResolvedStatus !== "ready") {
        return;
      }

      lastStableScopeKey.value = nextScopeKey;
      lastStableResolvedValues.value = cloneResolvedValues(nextResolvedValues);
    },
    { immediate: true, deep: true },
  );

  const resolvedValues = computed<ResolvedParameterPanelValues>(() => {
    if (resolvedStatus.value === "ready") {
      return rawResolvedValues.value;
    }

    if (
      resolvedStatus.value === "resolving" &&
      lastStableScopeKey.value === scopeKey.value &&
      lastStableResolvedValues.value
    ) {
      return cloneResolvedValues(lastStableResolvedValues.value);
    }

    return buildEmptyResolvedValues();
  });

  const displayValues = computed<ResolvedParameterPanelValues>(() => {
    const base = resolvedValues.value;

    return {
      renderProfile: {
        ...base.renderProfile,
        ...draftPatch.value.renderProfile,
      },
      voiceBinding: {
        ...base.voiceBinding,
        ...draftPatch.value.voiceBinding,
      },
      edge: base.edge
        ? {
            ...base.edge,
            ...draftPatch.value.edge,
          }
        : null,
    };
  });

  function syncAcceptedSelection() {
    acceptedSelectionSnapshot.value = selection.captureSelection();
  }

  function acceptDesiredScope() {
    scopeContext.value = cloneScopeContext(desiredScopeContext.value);
    pendingScopeContext.value = null;
    pendingSelectionSnapshot.value = null;
    confirmVisible.value = false;
    syncAcceptedSelection();
  }

  watch(
    desiredScopeContext,
    (nextScope) => {
      if (isSameScope(scopeContext.value, nextScope)) {
        syncAcceptedSelection();
        return;
      }

      if (!hasDirty.value) {
        scopeContext.value = cloneScopeContext(nextScope);
        syncAcceptedSelection();
        return;
      }

      pendingScopeContext.value = cloneScopeContext(nextScope);
      pendingSelectionSnapshot.value = selection.captureSelection();
      confirmVisible.value = true;
    },
    { deep: true, immediate: true },
  );

  function markDirty(fieldKey: string) {
    const nextSet = new Set(dirtyFieldSet.value);
    nextSet.add(fieldKey);
    dirtyFieldSet.value = nextSet;
  }

  function clearDirty(fieldKey: string) {
    const nextSet = new Set(dirtyFieldSet.value);
    nextSet.delete(fieldKey);
    dirtyFieldSet.value = nextSet;
  }

  function updateRenderProfileField<K extends keyof RenderProfilePatch>(
    key: K,
    value: RenderProfilePatch[K],
  ) {
    const isSameAsOriginal =
      value ===
      resolvedValues.value.renderProfile[
        key as keyof typeof resolvedValues.value.renderProfile
      ];
    const nextProfile = { ...draftPatch.value.renderProfile, [key]: value };
    if (isSameAsOriginal) {
      delete nextProfile[key];
    }
    
    draftPatch.value = {
      ...draftPatch.value,
      renderProfile: nextProfile,
    };

    const fieldKey = `renderProfile.${String(key)}`;
    if (isSameAsOriginal) {
      clearDirty(fieldKey);
    } else {
      markDirty(fieldKey);
    }
  }

  function updateVoiceBindingField<K extends keyof VoiceBindingPatch>(
    key: K,
    value: VoiceBindingPatch[K],
  ) {
    const isSameAsOriginal =
      value ===
      resolvedValues.value.voiceBinding[
        key as keyof typeof resolvedValues.value.voiceBinding
      ];
    const nextBinding = { ...draftPatch.value.voiceBinding, [key]: value };
    if (isSameAsOriginal) {
      delete nextBinding[key];
    }

    draftPatch.value = {
      ...draftPatch.value,
      voiceBinding: nextBinding,
    };

    const fieldKey = `voiceBinding.${String(key)}`;
    if (isSameAsOriginal) {
      clearDirty(fieldKey);
    } else {
      markDirty(fieldKey);
    }
  }

  function updateEdgeField<K extends keyof EdgeUpdateBody>(
    key: K,
    value: EdgeUpdateBody[K],
  ) {
    if (
      key === "boundary_strategy" &&
      resolvedValues.value.edge?.boundary_strategy_locked
    ) {
      return;
    }

    const isSameAsOriginal =
      resolvedValues.value.edge &&
      value ===
        resolvedValues.value.edge[
          key as keyof typeof resolvedValues.value.edge
        ];
    const nextEdge = { ...draftPatch.value.edge, [key]: value };
    if (isSameAsOriginal) {
      delete nextEdge[key];
    }

    draftPatch.value = {
      ...draftPatch.value,
      edge: nextEdge,
    };

    const fieldKey = `edge.${String(key)}`;
    if (isSameAsOriginal) {
      clearDirty(fieldKey);
    } else {
      markDirty(fieldKey);
    }
  }

  function discardDraft() {
    clearDraftState();
  }

  function buildEdgeSummary(): string {
    const currentEdge = resolvedValues.value.edge;
    if (!currentEdge) {
      return "边界参数调整";
    }

    if (draftPatch.value.edge.pause_duration_seconds != null) {
      return `停顿 ${currentEdge.pause_duration_seconds.toFixed(2)} -> ${draftPatch.value.edge.pause_duration_seconds.toFixed(2)}`;
    }

    if (draftPatch.value.edge.boundary_strategy) {
      return `边界策略 ${currentEdge.boundary_strategy} -> ${draftPatch.value.edge.boundary_strategy}`;
    }

    return "边界参数调整";
  }

  function assertEdgeDraftSafeToCommit() {
    const edgeId = scopeContext.value.edgeId;
    if (
      scopeContext.value.scope !== "edge" ||
      !edgeId ||
      !shouldBlockEdgeEditing({
        edgeId,
        edges: editSession.edges.value,
        dirtySegmentIds: lightEdit.dirtySegmentIds.value,
      })
    ) {
      return;
    }

    const message = "该停顿会影响待重推理段，请先重推理";
    ElMessage.warning(message);
    throw new Error(message);
  }

  function buildPatchTasks() {
    const tasks: Array<{
      kind: "voice-binding" | "render-profile" | "edge";
      submit: () => Promise<void>;
    }> = [];

    if (scopeContext.value.scope === "session" || scopeContext.value.scope === "segment" || scopeContext.value.scope === "batch") {
      if (Object.keys(draftPatch.value.voiceBinding).length > 0) {
        tasks.push({
          kind: "voice-binding",
          submit: async () => {
            if (scopeContext.value.scope === "session") {
              await commitSessionVoiceBinding(draftPatch.value.voiceBinding);
              return;
            }
            if (scopeContext.value.scope === "segment") {
              await commitSegmentVoiceBinding(scopeContext.value.segmentIds[0], draftPatch.value.voiceBinding);
              return;
            }
            await commitSegmentVoiceBindingBatch({
              segment_ids: scopeContext.value.segmentIds,
              patch: draftPatch.value.voiceBinding,
            });
          },
        });
      }

      if (Object.keys(draftPatch.value.renderProfile).length > 0) {
        tasks.push({
          kind: "render-profile",
          submit: async () => {
            if (scopeContext.value.scope === "session") {
              await commitSessionRenderProfile(draftPatch.value.renderProfile);
              return;
            }
            if (scopeContext.value.scope === "segment") {
              await commitSegmentRenderProfile(
                scopeContext.value.segmentIds[0],
                draftPatch.value.renderProfile,
              );
              return;
            }
            await commitSegmentRenderProfileBatch({
              segment_ids: scopeContext.value.segmentIds,
              patch: draftPatch.value.renderProfile,
            });
          },
        });
      }
    }

    if (scopeContext.value.scope === "edge" && scopeContext.value.edgeId && Object.keys(draftPatch.value.edge).length > 0) {
      tasks.push({
        kind: "edge",
        submit: async () => {
          assertEdgeDraftSafeToCommit();
          const completion = workspaceProcessing.startEdgeUpdate({
            summary: buildEdgeSummary(),
          });
          let jobResponse;
          try {
            jobResponse = await updateEdge(
              scopeContext.value.edgeId!,
              draftPatch.value.edge,
            );
          } catch (error) {
            workspaceProcessing.fail(
              error instanceof Error ? error.message : "停顿调整提交失败",
            );
            throw error;
          }
          workspaceProcessing.acceptJob({
            job: jobResponse,
            jobKind: "edge-compose",
          });
          runtimeState.trackJob(jobResponse, {
            initialRendering: false,
            refreshSessionOnTerminal: false,
          });
          await completion;
        },
      });
    }

    return tasks;
  }

  async function submitDraft() {
    if (!hasDirty.value) {
      return;
    }
    if (!runtimeState.canMutate.value || workspaceProcessing.isInteractionLocked.value) {
      throw new Error("当前存在活动作业，暂时不能提交参数");
    }

    const tasks = buildPatchTasks();
    if (tasks.length === 0) {
      clearDraftState();
      return;
    }

    isSubmitting.value = true;
    try {
      const result = await queue.run(tasks);
      if (result.status !== "completed") {
        if (result.error instanceof Error) {
          throw result.error;
        }
        throw new Error(`参数提交失败，失败阶段为 ${result.failedTaskKind ?? "unknown"}`);
      }

      if (scopeContext.value.scope !== "edge") {
        await editSession.refreshFormalSessionState();
      }
      clearDraftState();
      if (pendingScopeContext.value) {
        acceptDesiredScope();
      } else {
        syncAcceptedSelection();
      }
    } finally {
      isSubmitting.value = false;
    }
  }

  function cancelPendingScopeChange() {
    if (confirmVisible.value) {
      selection.restoreSelection(acceptedSelectionSnapshot.value);
      pendingScopeContext.value = null;
      pendingSelectionSnapshot.value = null;
      confirmVisible.value = false;
    }
  }

  async function discardAndContinue() {
    discardDraft();
    if (pendingScopeContext.value && pendingSelectionSnapshot.value) {
      acceptDesiredScope();
    }
  }

  async function submitAndContinue() {
    await submitDraft();
    if (pendingScopeContext.value && pendingSelectionSnapshot.value) {
      acceptDesiredScope();
    }
  }

  function triggerFlash() {
    flashPulse.value++;
  }

  return {
    scopeContext: computed(() => cloneScopeContext(scopeContext.value)),
    resolvedValues,
    resolvedStatus,
    displayValues,
    draftPatch: computed(() => draftPatch.value),
    dirtyFields: dirtyFieldSetReadonly,
    dirtyFieldList: dirtyFields,
    dirtyEdgeIds,
    hasDirty,
    isSubmitting,
    confirmVisible,
    flashPulse: computed(() => flashPulse.value),
    pendingScopeContext: computed(() =>
      pendingScopeContext.value
        ? cloneScopeContext(pendingScopeContext.value)
        : null,
    ),
    updateRenderProfileField,
    updateVoiceBindingField,
    updateEdgeField,
    discardDraft,
    submitDraft,
    cancelPendingScopeChange,
    discardAndContinue,
    submitAndContinue,
    triggerFlash,
  };
}
