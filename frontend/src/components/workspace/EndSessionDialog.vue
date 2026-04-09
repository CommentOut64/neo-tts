<script setup lang="ts">
import { computed } from "vue";
import type { EndSessionChoice, EndSessionGuard } from "./sessionHandoff";

const props = defineProps<{
  visible: boolean;
  mode: EndSessionGuard;
  loading?: boolean;
}>();

const emit = defineEmits<{
  (e: "update:visible", value: boolean): void;
  (e: "choose", value: EndSessionChoice): void;
}>();

function handleChoose(choice: EndSessionChoice) {
  emit("choose", choice);
}

const hasPendingChanges = computed(() => props.mode !== "confirm_plain");
const dialogTitle = computed(() =>
  hasPendingChanges.value ? "这些修改还没重推理到音频" : "结束当前会话？",
);
</script>

<template>
  <el-dialog
    :model-value="visible"
    width="520px"
    :close-on-click-modal="false"
    :close-on-press-escape="!loading"
    :show-close="!loading"
    :lock-scroll="false"
    :title="dialogTitle"
    @update:model-value="emit('update:visible', $event)"
  >
    <div class="space-y-3 py-2 text-sm text-foreground/80">
      <p v-if="mode === 'confirm_with_text_options'">
        现在结束会话，这些修改不会进入当前音频。你可以继续编辑、保留文字并结束会话，或撤销这些修改后结束会话。
      </p>
      <p v-else-if="mode === 'confirm_discard_only'">
        现在结束会话，这些修改不会进入当前音频。你可以继续编辑，或直接结束当前会话。
      </p>
      <p v-else>当前没有待重推理修改。结束当前会话后，将回到首次生成前。</p>
    </div>

    <template #footer>
      <div class="flex flex-wrap justify-end gap-2">
        <el-button :disabled="loading" @click="handleChoose('continue_editing')">
          继续编辑
        </el-button>
        <el-button
          v-if="mode === 'confirm_with_text_options'"
          :disabled="loading"
          @click="handleChoose('discard_unapplied_changes')"
        >
          放弃修改
        </el-button>
        <el-button
          type="danger"
          :loading="loading"
          :disabled="loading"
          @click="handleChoose(mode === 'confirm_with_text_options' ? 'keep_working_text' : 'discard_unapplied_changes')"
        >
          {{ mode === "confirm_with_text_options" ? "保留文字" : "结束当前会话" }}
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>
