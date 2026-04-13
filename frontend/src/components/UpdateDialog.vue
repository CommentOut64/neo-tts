<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="$emit('update:visible', $event)"
    title="发现新版本"
    width="400px"
    top="20vh"
    append-to-body
    class="update-dialog"
    :close-on-click-modal="false"
  >
    <div v-if="updateInfo" class="update-content">
      <h3 class="version-title">Neo TTS {{ updateInfo.latest_version }}</h3>
      <div class="release-notes">
        <p>{{ updateInfo.release_notes }}</p>
      </div>
    </div>
    <template #footer>
      <div class="dialog-footer">
        <el-button @click="$emit('ignore')">忽略此版本</el-button>
        <el-button type="primary" @click="goDownload">前往下载</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import type { UpdateCheckResult } from "@/api/system";

const props = defineProps<{
  visible: boolean;
  updateInfo: UpdateCheckResult | null;
}>();

const emit = defineEmits(["update:visible", "ignore"]);

function goDownload() {
  if (props.updateInfo?.download_url) {
    window.open(props.updateInfo.download_url, "_blank");
  }
}
</script>

<style scoped>
.update-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.version-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--color-foreground);
}

.release-notes {
  font-size: 14px;
  color: var(--color-muted-fg);
  background: var(--color-secondary);
  padding: 12px;
  border-radius: 6px;
  white-space: pre-wrap;
  line-height: 1.5;
}
</style>
