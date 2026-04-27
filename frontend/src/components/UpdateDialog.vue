<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="$emit('update:visible', $event)"
    :title="dialogTitle"
    width="420px"
    top="20vh"
    append-to-body
    class="update-dialog"
    :close-on-click-modal="state.status !== 'switching'"
  >
    <div class="update-content">
      <template v-if="state.releaseId">
        <h3 class="version-title">Neo TTS {{ state.releaseId }}</h3>
      </template>

      <p v-if="state.status === 'bootstrap-upgrade-required'" class="summary-text">
        当前启动器版本过低，至少需要 {{ state.minBootstrapVersion }} 才能应用此版本更新。
      </p>

      <p v-else-if="state.status === 'ready-to-restart'" class="summary-text">
        更新已完成分层 staging，关闭当前应用后即可切换到新版本。
      </p>

      <p v-else-if="state.status === 'downloading'" class="summary-text">
        正在准备分层更新，请稍候。{{ progressSummary }}
      </p>

      <p v-else-if="state.status === 'switching'" class="summary-text">
        正在请求重启并应用更新。
      </p>

      <p v-else-if="state.status === 'error'" class="summary-text error-text">
        {{ errorSummary }}
      </p>

      <p v-else class="summary-text">
        检测到新的分层更新，以下层包会在本次更新中替换：
      </p>

      <div v-if="state.changedPackages?.length" class="package-section">
        <div class="package-title">本次会替换的层包</div>
        <ul class="package-list">
          <li v-for="packageId in state.changedPackages" :key="packageId">
            {{ packageLabel(packageId) }}
          </li>
        </ul>
      </div>

      <div
        v-if="state.progress && (state.status === 'downloading' || state.status === 'ready-to-restart')"
        class="meta-line"
      >
        进度：{{ state.progress.completedPackages }} / {{ state.progress.totalPackages }}
        <template v-if="state.progress.currentPackageId">
          ，当前层 {{ packageLabel(state.progress.currentPackageId) }}
        </template>
      </div>

      <div v-if="state.estimatedDownloadBytes" class="meta-line">
        预计下载体积 {{ formatBytes(state.estimatedDownloadBytes) }}
      </div>

      <div v-if="state.notesUrl" class="meta-line">
        <a class="notes-link" :href="state.notesUrl" target="_blank" rel="noreferrer">
          查看发布说明
        </a>
      </div>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <el-button
          v-if="state.status === 'update-available' || state.status === 'bootstrap-upgrade-required'"
          @click="$emit('ignore')"
        >
          忽略此版本
        </el-button>
        <el-button
          v-if="state.status === 'update-available'"
          type="primary"
          @click="$emit('start-download')"
        >
          立即下载
        </el-button>
        <el-button
          v-else-if="state.status === 'downloading'"
          type="primary"
          disabled
        >
          下载中...
        </el-button>
        <el-button
          v-else-if="state.status === 'ready-to-restart'"
          type="primary"
          @click="$emit('restart-now')"
        >
          立即重启并更新
        </el-button>
        <el-button
          v-else-if="state.status === 'switching'"
          type="primary"
          disabled
        >
          正在重启...
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { AppUpdateState } from "@/types/update";

const props = defineProps<{
  visible: boolean;
  state: AppUpdateState;
}>();

defineEmits(["update:visible", "ignore", "start-download", "restart-now"]);

const dialogTitle = computed(() => {
  switch (props.state.status) {
    case "bootstrap-upgrade-required":
      return "需要先升级启动器";
    case "ready-to-restart":
      return "更新已准备就绪";
    case "downloading":
      return "正在准备更新";
    case "switching":
      return "正在应用更新";
    case "error":
      return "更新失败";
    default:
      return "发现新版本";
  }
});

const progressSummary = computed(() => {
  const progress = props.state.progress;
  if (!progress) {
    return "已开始下载层包。";
  }
  const completed = `${progress.completedPackages} / ${progress.totalPackages}`;
  if (progress.currentPackageId) {
    return `已完成 ${completed}，当前层 ${packageLabel(progress.currentPackageId)}。`;
  }
  return `已完成 ${completed}。`;
});

const errorSummary = computed(() => {
  if (props.state.errorCode === "switch-failed") {
    return props.state.errorMessage || "上次更新失败，已回滚到当前稳定版本，可稍后重试。";
  }
  return props.state.errorMessage || "更新失败，请稍后重试。";
});

function formatBytes(sizeBytes: number): string {
  if (sizeBytes >= 1024 * 1024) {
    return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (sizeBytes >= 1024) {
    return `${(sizeBytes / 1024).toFixed(1)} KB`;
  }
  return `${sizeBytes} B`;
}

function packageLabel(packageId: string): string {
  const labels: Record<string, string> = {
    bootstrap: "bootstrap 启动器",
    "update-agent": "update-agent 替换器",
    shell: "桌面壳层",
    "app-core": "应用核心层",
    runtime: "运行时层",
    models: "内置模型层",
    "pretrained-models": "预训练模型层",
  };
  return labels[packageId] ?? packageId;
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

.summary-text {
  margin: 0;
  font-size: 14px;
  color: var(--color-muted-fg);
  line-height: 1.6;
}

.error-text {
  color: var(--color-danger, #c0392b);
}

.package-section {
  background: var(--color-secondary);
  padding: 12px;
  border-radius: 6px;
}

.package-title {
  font-size: 12px;
  color: var(--color-muted-fg);
  margin-bottom: 6px;
}

.package-list {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.meta-line {
  font-size: 12px;
  color: var(--color-muted-fg);
  word-break: break-all;
}

.notes-link {
  color: var(--color-cta);
  text-decoration: none;
}
</style>
