import { computed, ref, watch } from "vue";

import {
  commitEdgeConfig,
  commitSegmentRenderProfile,
  commitSegmentRenderProfileBatch,
  commitSegmentVoiceBinding,
  commitSegmentVoiceBindingBatch,
  commitSessionRenderProfile,
  commitSessionVoiceBinding,
} from "@/api/editSession";
import { useEditSession } from "@/composables/useEditSession";
import { useRuntimeState } from "@/composables/useRuntimeState";
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

export function useParameterPanel() {
  const editSession = useEditSession();
  const runtimeState = useRuntimeState();
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

  const resolvedValues = computed<ResolvedParameterPanelValues>(() =>
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
          await commitEdgeConfig(scopeContext.value.edgeId!, draftPatch.value.edge);
        },
      });
    }

    return tasks;
  }

  async function submitDraft() {
    if (!hasDirty.value) {
      return;
    }
    if (!runtimeState.canMutate.value) {
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
        throw new Error(`参数提交失败，失败阶段为 ${result.failedTaskKind ?? "unknown"}`);
      }

      await editSession.refreshSnapshot();
      if (editSession.sessionStatus.value === "ready") {
        await editSession.refreshTimeline();
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
    displayValues,
    draftPatch: computed(() => draftPatch.value),
    dirtyFields: dirtyFieldSetReadonly,
    dirtyFieldList: dirtyFields,
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
