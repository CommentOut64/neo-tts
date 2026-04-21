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
import {
  MIXED_VALUE,
  resolveEffectiveParameters,
  type ResolvedParameterPanelValues,
} from "@/components/workspace/parameter-panel/resolveEffectiveParameters";
import { shouldBlockEdgeEditing } from "@/components/workspace/workspace-editor/workspaceEditorHostModel";
import { useEditSession } from "@/composables/useEditSession";
import { useRuntimeState } from "@/composables/useRuntimeState";
import {
  useSegmentSelection,
  type SelectionSnapshot,
} from "@/composables/useSegmentSelection";
import { useWorkspaceLightEdit } from "@/composables/useWorkspaceLightEdit";
import { useWorkspaceProcessing } from "@/composables/useWorkspaceProcessing";
import { createParameterPatchQueue } from "@/components/workspace/parameter-panel/submitParameterPatchQueue";
import { resolveBindingReferenceState } from "@/features/reference-binding";
import {
  resolveParameterScope,
  type ParameterPanelScopeContext,
} from "@/components/workspace/parameter-panel/resolveParameterScope";
import type {
  EdgeUpdateBody,
  ReferenceAudioUploadResponse,
  ReferenceBindingOverridePatch,
  RenderProfile,
  RenderProfilePatch,
  VoiceBinding,
  VoiceBindingPatch,
} from "@/types/editSession";
import type { VoiceProfile } from "@/types/tts";

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
const availableVoices = ref<VoiceProfile[]>([]);
const referenceSourceIntent = ref<"preset" | "custom" | null>(null);

type ParameterPanelResolvedStatus = "ready" | "resolving" | "unresolved";
type ReferenceFieldKey =
  | "reference_audio_path"
  | "reference_text"
  | "reference_language";

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
  referenceSourceIntent.value = null;
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
    },
    voiceBinding: {
      voice_id: null,
      model_key: null,
      gpt_path: null,
      sovits_path: null,
    },
    reference: {
      source: null,
      reference_scope: null,
      binding_key: null,
      reference_identity: null,
      session_reference_asset_id: null,
      reference_audio_fingerprint: null,
      reference_audio_path: null,
      reference_text: null,
      reference_text_fingerprint: null,
      reference_language: null,
      preset_audio_path: null,
      preset_text: null,
      preset_language: null,
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
    reference: {
      ...values.reference,
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

function isMixedValue(value: unknown): value is typeof MIXED_VALUE {
  return value === MIXED_VALUE;
}

function isConcreteString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function setVoices(voices: VoiceProfile[]) {
  availableVoices.value = [...voices];
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
      voices: availableVoices.value,
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
    const displayBinding = {
      ...base.voiceBinding,
      ...draftPatch.value.voiceBinding,
    };
    const displayProfile = {
      speed: draftPatch.value.renderProfile.speed ?? base.renderProfile.speed,
      top_k: draftPatch.value.renderProfile.top_k ?? base.renderProfile.top_k,
      top_p: draftPatch.value.renderProfile.top_p ?? base.renderProfile.top_p,
      temperature: draftPatch.value.renderProfile.temperature ?? base.renderProfile.temperature,
      noise_scale: draftPatch.value.renderProfile.noise_scale ?? base.renderProfile.noise_scale,
    };

    return {
      renderProfile: displayProfile,
      voiceBinding: displayBinding,
      reference: buildDisplayReference({
        base,
        displayBinding,
        currentScope: scopeContext.value,
        renderProfiles: editSession.renderProfiles.value,
        snapshot: editSession.snapshot.value,
        segments: editSession.segments.value,
        groups: editSession.groups.value,
        draftReferenceOverride: draftPatch.value.renderProfile.reference_override ?? null,
      }),
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
    referenceSourceIntent.value = null;
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

  function updateReferenceSource(source: "preset" | "custom") {
    const currentBindingKey = getActiveBindingKey();
    if (!currentBindingKey) {
      return;
    }

    if (source === "custom") {
      referenceSourceIntent.value = "custom";

      if (draftPatch.value.renderProfile.reference_override?.operation === "clear") {
        replaceReferenceOverride(null);
      }

      if (resolvedValues.value.reference.source === "custom") {
        clearDirty("reference.source");
      }
      return;
    }

    referenceSourceIntent.value = "preset";
    const baseReference = resolvedValues.value.reference;
    if (
      baseReference.binding_key === currentBindingKey &&
      baseReference.source === "preset"
    ) {
      replaceReferenceOverride(null);
      clearDirty("reference.source");
      clearDirty("reference.reference_audio_path");
      clearDirty("reference.reference_text");
      clearDirty("reference.reference_language");
      return;
    }

    replaceReferenceOverride({
      binding_key: currentBindingKey,
      operation: "clear",
    });
    markDirty("reference.source");
  }

  function updateReferenceField(
    field: ReferenceFieldKey,
    value: string | null,
  ) {
    const currentBindingKey = getActiveBindingKey();
    if (!currentBindingKey) {
      return;
    }

    referenceSourceIntent.value = "custom";
    const currentReference = displayValues.value.reference;
    const nextOverride: ReferenceBindingOverridePatch = {
      binding_key: currentBindingKey,
      operation: "upsert",
      reference_identity:
        field === "reference_audio_path"
          ? null
          : normalizeReferenceFieldValue(currentReference.reference_identity),
      session_reference_asset_id:
        field === "reference_audio_path"
          ? null
          : normalizeReferenceFieldValue(
              currentReference.session_reference_asset_id,
            ),
      reference_audio_fingerprint:
        field === "reference_audio_path"
          ? null
          : normalizeReferenceFieldValue(
              currentReference.reference_audio_fingerprint,
            ),
      reference_audio_path:
        field === "reference_audio_path"
          ? value
          : normalizeReferenceFieldValue(currentReference.reference_audio_path),
      reference_text:
        field === "reference_text"
          ? value
          : normalizeReferenceFieldValue(currentReference.reference_text),
      reference_text_fingerprint:
        field === "reference_text"
          ? null
          : normalizeReferenceFieldValue(
              currentReference.reference_text_fingerprint,
            ),
      reference_language:
        field === "reference_language"
          ? value
          : normalizeReferenceFieldValue(currentReference.reference_language),
    };

    replaceReferenceOverride(nextOverride);
    markDirty(`reference.${field}`);
    if (resolvedValues.value.reference.source !== "custom") {
      markDirty("reference.source");
    }
  }

  function applyUploadedReferenceAudio(
    response: ReferenceAudioUploadResponse,
  ) {
    const currentBindingKey = getActiveBindingKey();
    if (!currentBindingKey) {
      return;
    }

    referenceSourceIntent.value = "custom";
    const currentReference = displayValues.value.reference;
    replaceReferenceOverride({
      binding_key: currentBindingKey,
      operation: "upsert",
      session_reference_asset_id: response.reference_asset_id,
      reference_identity: response.reference_identity,
      reference_audio_fingerprint: response.reference_audio_fingerprint,
      reference_audio_path: response.reference_audio_path,
      reference_text: normalizeReferenceFieldValue(currentReference.reference_text),
      reference_text_fingerprint: response.reference_text_fingerprint,
      reference_language: normalizeReferenceFieldValue(currentReference.reference_language),
    });
    markDirty("reference.source");
    markDirty("reference.reference_audio_path");
  }

  function replaceReferenceOverride(
    nextOverride: RenderProfilePatch["reference_override"] | null,
  ) {
    const nextProfile = { ...draftPatch.value.renderProfile };
    if (nextOverride) {
      nextProfile.reference_override = nextOverride;
    } else {
      delete nextProfile.reference_override;
    }

    draftPatch.value = {
      ...draftPatch.value,
      renderProfile: nextProfile,
    };
  }

  function getActiveBindingKey(): string | null {
    const displayBinding = displayValues.value.voiceBinding;
    if (
      !isConcreteString(displayBinding.voice_id) ||
      !isConcreteString(displayBinding.model_key) ||
      isMixedValue(displayBinding.voice_id) ||
      isMixedValue(displayBinding.model_key)
    ) {
      return null;
    }

    return `${displayBinding.voice_id}:${displayBinding.model_key}`;
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

    if (
      scopeContext.value.scope === "session" ||
      scopeContext.value.scope === "segment" ||
      scopeContext.value.scope === "batch"
    ) {
      if (Object.keys(draftPatch.value.voiceBinding).length > 0) {
        tasks.push({
          kind: "voice-binding",
          submit: async () => {
            if (scopeContext.value.scope === "session") {
              await commitSessionVoiceBinding(draftPatch.value.voiceBinding);
              return;
            }
            if (scopeContext.value.scope === "segment") {
              await commitSegmentVoiceBinding(
                scopeContext.value.segmentIds[0],
                draftPatch.value.voiceBinding,
              );
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

    if (
      scopeContext.value.scope === "edge" &&
      scopeContext.value.edgeId &&
      Object.keys(draftPatch.value.edge).length > 0
    ) {
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
    if (
      !runtimeState.canMutate.value ||
      workspaceProcessing.isInteractionLocked.value
    ) {
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
    setVoices,
    updateRenderProfileField,
    updateVoiceBindingField,
    updateReferenceSource,
    updateReferenceField,
    applyUploadedReferenceAudio,
    updateEdgeField,
    discardDraft,
    submitDraft,
    cancelPendingScopeChange,
    discardAndContinue,
    submitAndContinue,
    triggerFlash,
  };
}

function normalizeReferenceFieldValue(
  value: string | typeof MIXED_VALUE | null,
): string | null {
  if (value === null || value === MIXED_VALUE) {
    return null;
  }
  return value;
}

function buildDisplayReference(input: {
  base: ResolvedParameterPanelValues;
  displayBinding: ResolvedParameterPanelValues["voiceBinding"];
  currentScope: ParameterPanelScopeContext;
  renderProfiles: RenderProfile[];
  snapshot: {
    default_render_profile_id?: string | null;
  } | null;
  segments: Array<{
    segment_id: string;
    group_id: string | null;
    render_profile_id: string | null;
  }>;
  groups: Array<{
    group_id: string;
    render_profile_id: string | null;
  }>;
  draftReferenceOverride: ReferenceBindingOverridePatch | null;
}): ResolvedParameterPanelValues["reference"] {
  if (
    !isConcreteString(input.displayBinding.voice_id) ||
    !isConcreteString(input.displayBinding.model_key) ||
    isMixedValue(input.displayBinding.voice_id) ||
    isMixedValue(input.displayBinding.model_key)
  ) {
    return input.base.reference;
  }

  const baseProfiles = resolveScopeRenderProfiles({
    currentScope: input.currentScope,
    renderProfiles: input.renderProfiles,
    snapshot: input.snapshot,
    segments: input.segments,
    groups: input.groups,
  });
  const resolvedStates = baseProfiles.map((profile) =>
    resolveBindingReferenceState({
      binding: {
        voice_id: input.displayBinding.voice_id,
        model_key: input.displayBinding.model_key,
      } as VoiceBinding,
      profile: applyReferenceOverrideDraft(
        profile,
        input.draftReferenceOverride,
      ),
      voices: availableVoices.value,
    }),
  );
  const resolved = pickDisplayReferenceState(resolvedStates);

  if (referenceSourceIntent.value === "custom" && resolved.source === "preset") {
    return {
      ...resolved,
      source: "custom",
    };
  }

  if (referenceSourceIntent.value === "preset") {
    return {
      ...resolved,
      source: "preset",
    };
  }

  return resolved;
}

function resolveScopeRenderProfiles(input: {
  currentScope: ParameterPanelScopeContext;
  renderProfiles: RenderProfile[];
  snapshot: {
    default_render_profile_id?: string | null;
  } | null;
  segments: Array<{
    segment_id: string;
    group_id: string | null;
    render_profile_id: string | null;
  }>;
  groups: Array<{
    group_id: string;
    render_profile_id: string | null;
  }>;
}): RenderProfile[] {
  const profileById = new Map(
    input.renderProfiles.map((profile) => [profile.render_profile_id, profile] as const),
  );
  const groupById = new Map(
    input.groups.map((group) => [group.group_id, group] as const),
  );
  const defaultProfileId = input.snapshot?.default_render_profile_id ?? null;

  if (input.currentScope.scope === "segment" || input.currentScope.scope === "batch") {
    return input.currentScope.segmentIds
      .map((segmentId) => {
        const segment = input.segments.find((item) => item.segment_id === segmentId);
        let profileId = defaultProfileId;
        if (segment?.group_id) {
          profileId = groupById.get(segment.group_id)?.render_profile_id ?? profileId;
        }
        profileId = segment?.render_profile_id ?? profileId;
        return profileId ? profileById.get(profileId) ?? null : null;
      })
      .filter((profile): profile is RenderProfile => profile !== null);
  }

  return defaultProfileId ? [profileById.get(defaultProfileId) ?? null].filter((profile): profile is RenderProfile => profile !== null) : [];
}

function applyReferenceOverrideDraft(
  profile: RenderProfile | null,
  draftReferenceOverride: ReferenceBindingOverridePatch | null,
): RenderProfile | null {
  if (!profile || !draftReferenceOverride?.binding_key) {
    return profile;
  }

  const nextOverrides = { ...profile.reference_overrides_by_binding };
  if (draftReferenceOverride.operation === "clear") {
    delete nextOverrides[draftReferenceOverride.binding_key];
  } else {
    nextOverrides[draftReferenceOverride.binding_key] = {
      session_reference_asset_id: draftReferenceOverride.session_reference_asset_id ?? null,
      reference_identity: draftReferenceOverride.reference_identity ?? null,
      reference_audio_fingerprint: draftReferenceOverride.reference_audio_fingerprint ?? null,
      reference_audio_path: draftReferenceOverride.reference_audio_path ?? null,
      reference_text: draftReferenceOverride.reference_text ?? null,
      reference_text_fingerprint: draftReferenceOverride.reference_text_fingerprint ?? null,
      reference_language: draftReferenceOverride.reference_language ?? null,
    };
  }

  return {
    ...profile,
    reference_overrides_by_binding: nextOverrides,
  };
}

function pickDisplayReferenceState(
  states: Array<ReturnType<typeof resolveBindingReferenceState>>,
): ResolvedParameterPanelValues["reference"] {
  if (states.length === 0) {
    return {
      source: null,
      reference_scope: null,
      binding_key: null,
      reference_identity: null,
      session_reference_asset_id: null,
      reference_audio_fingerprint: null,
      reference_audio_path: null,
      reference_text: null,
      reference_text_fingerprint: null,
      reference_language: null,
      preset_audio_path: null,
      preset_text: null,
      preset_language: null,
    };
  }

  const pickValue = <T>(values: T[]): T | typeof MIXED_VALUE | null => {
    const first = values[0];
    return values.every((value) => value === first) ? first : MIXED_VALUE;
  };

  return {
    source: pickValue(states.map((state) => state.source)),
    reference_scope: pickValue(states.map((state) => state.reference_scope)),
    binding_key: pickValue(states.map((state) => state.binding_key)),
    reference_identity: pickValue(states.map((state) => state.reference_identity)),
    session_reference_asset_id: pickValue(states.map((state) => state.session_reference_asset_id)),
    reference_audio_fingerprint: pickValue(states.map((state) => state.reference_audio_fingerprint)),
    reference_audio_path: pickValue(states.map((state) => state.reference_audio_path)),
    reference_text: pickValue(states.map((state) => state.reference_text)),
    reference_text_fingerprint: pickValue(states.map((state) => state.reference_text_fingerprint)),
    reference_language: pickValue(states.map((state) => state.reference_language)),
    preset_audio_path: pickValue(states.map((state) => state.preset_audio_path)),
    preset_text: pickValue(states.map((state) => state.preset_text)),
    preset_language: pickValue(states.map((state) => state.preset_language)),
  };
}
