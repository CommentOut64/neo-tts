import { computed, ref } from "vue";

function arraysEqual(left: string[], right: string[]) {
  return (
    left.length === right.length &&
    left.every((value, index) => value === right[index])
  );
}

const stagedOrder = ref<string[] | null>(null);
const isSubmitting = ref(false);
const applyHandler = ref<null | (() => Promise<void>)>(null);
const discardHandler = ref<null | (() => void)>(null);

export function useWorkspaceReorderDraft() {
  function setStagedOrder(nextOrder: string[], committedOrder: string[]) {
    if (arraysEqual(nextOrder, committedOrder)) {
      stagedOrder.value = null;
      return false;
    }

    stagedOrder.value = [...nextOrder];
    return true;
  }

  function clearDraft() {
    stagedOrder.value = null;
    isSubmitting.value = false;
  }

  function startSubmitting() {
    isSubmitting.value = true;
  }

  function finishSubmitting() {
    isSubmitting.value = false;
  }

  function registerActions(actions: {
    applyDraft: () => Promise<void>;
    discardDraft: () => void;
  }) {
    applyHandler.value = actions.applyDraft;
    discardHandler.value = actions.discardDraft;

    return () => {
      if (applyHandler.value === actions.applyDraft) {
        applyHandler.value = null;
      }
      if (discardHandler.value === actions.discardDraft) {
        discardHandler.value = null;
      }
    };
  }

  async function requestApplyDraft() {
    if (!applyHandler.value) {
      throw new Error("当前没有可应用的顺序调整");
    }
    await applyHandler.value();
  }

  function requestDiscardDraft() {
    if (!discardHandler.value) {
      return;
    }
    discardHandler.value();
  }

  return {
    stagedOrder: computed(() =>
      stagedOrder.value ? [...stagedOrder.value] : null,
    ),
    hasDraft: computed(() => stagedOrder.value !== null),
    isSubmitting: computed(() => isSubmitting.value),
    setStagedOrder,
    clearDraft,
    startSubmitting,
    finishSubmitting,
    registerActions,
    requestApplyDraft,
    requestDiscardDraft,
  };
}
