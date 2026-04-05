<script setup lang="ts">
import { ref, watch, onMounted, nextTick } from "vue";
import { useWorkspaceLightEdit } from "@/composables/useWorkspaceLightEdit";
// Assuming UEditor and UButton are auto-imported or globally registered by @nuxt/ui module

const props = defineProps<{
  segmentId: string;
  initialText: string;
}>();

const emit = defineEmits<{
  (e: "exit-edit"): void;
}>();

const lightEdit = useWorkspaceLightEdit();

// Local state
const isEditing = ref(true);
const editorContent = ref(props.initialText);

// Initialize editor content with draft if it exists, otherwise initialText
onMounted(() => {
  const draft = lightEdit.getDraft(props.segmentId);
  if (draft !== undefined) {
    editorContent.value = draft;
  }
});

// Auto-focus on mount by UEditor config or manual if required

const handleComplete = () => {
  const currentHtml = editorContent.value?.trim() || ""; // This assumes UEditor outputs HTML or text. For simplicity assumed text/HTML.
  const cleanedText = currentHtml.replace(/<[^>]*>?/gm, ""); // Strip basic HTML tags if UEditor outputs rich text but we need plain string for backend
  const finalText = currentHtml.includes("<") ? cleanedText : currentHtml;

  if (finalText !== props.initialText) {
    lightEdit.setDraft(props.segmentId, finalText);
  } else {
    // If user edited back to original, maybe clear it? But checking exact string is fine for now.
    // lightEdit.clearDraft(props.segmentId)
    // We strictly record the exact final HTML or text as the draft. But since this is "light edit", text is probably sufficient.
    lightEdit.setDraft(props.segmentId, finalText);
  }

  isEditing.value = false;
  emit("exit-edit");
};

const handleCancel = () => {
  isEditing.value = false;
  emit("exit-edit");
};

const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === "Escape") {
    // Save draft and exit on Escape per plan "Esc或完成编辑退出"
    handleComplete();
  }
};
</script>

<template>
  <div
    class="relative w-full border border-primary/40 rounded-md p-2 bg-background shadow-sm focus-within:border-primary/80 transition-colors z-10"
    @keydown="handleKeyDown"
  >
    <!-- Inline Nuxt UI Editor -->
    <!-- UEditor component expected by @nuxt/ui -->
    <UEditor
      v-model="editorContent"
      class="min-h-[40px] text-sm focus:outline-none"
    />

    <!-- Editor Action Footer -->
    <div
      class="flex items-center justify-end gap-2 mt-2 pt-2 border-t border-border/50"
    >
      <button
        type="button"
        @click="handleCancel"
        class="px-2 py-1 text-xs font-medium rounded text-muted-fg hover:bg-secondary/50 transition-colors"
      >
        取消
      </button>
      <button
        type="button"
        @click="handleComplete"
        class="px-3 py-1 space-x-1 text-xs font-semibold rounded bg-blue-500 text-white hover:bg-blue-600 transition-colors shadow-sm"
      >
        <span
          class="i-lucide-check w-3.5 h-3.5 inline-block align-text-bottom"
        ></span>
        <span>完成</span>
      </button>
    </div>
  </div>
</template>
