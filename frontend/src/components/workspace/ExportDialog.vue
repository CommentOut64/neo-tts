<script setup lang="ts">
import { ref, computed, onBeforeUnmount } from "vue";
import { ElMessage } from "element-plus";
import {
  exportSegments,
  exportComposition,
  subscribeExportJobEvents,
  getExportJob,
} from "@/api/editSession";
import { openFolderDialog } from "@/api/system";
import { extractStatusCode } from "@/api/requestSupport";
import { useEditSession } from "@/composables/useEditSession";
import { useRuntimeState } from "@/composables/useRuntimeState";
import { isExportBlockedByRenderJob } from "./sessionHandoff";
import type { ExportJobResponse } from "@/types/editSession";

defineProps<{
  visible: boolean;
}>();

const emit = defineEmits<{
  (e: "update:visible", value: boolean): void;
}>();

const { snapshot } = useEditSession();
const { currentRenderJob, trackExportJob } = useRuntimeState();

const exportType = ref<"composition" | "segments">("composition");
const targetDir = ref("");
const isExporting = ref(false);
const progress = ref(0);
const statusMessage = ref("");
const resultFiles = ref<string[]>([]);
let unsubscribe: (() => void) | null = null;
let pollingIntervalId: ReturnType<typeof setInterval> | null = null;

const documentVersion = computed(
  () => snapshot.value?.document_version ?? null,
);
const isRenderBlocked = computed(() =>
  isExportBlockedByRenderJob(currentRenderJob.value),
);
const canStartExport = computed(
  () => documentVersion.value != null && !isRenderBlocked.value,
);
const footerButtonLabel = computed(() =>
  resultFiles.value.length > 0 ? "重新导出" : "开始导出",
);

async function startExport() {
  if (!targetDir.value.trim()) {
    ElMessage.warning("请输入或选择导出根目录（绝对路径）");
    return;
  }
  if (documentVersion.value == null) {
    ElMessage.warning("没有可导出的版本");
    return;
  }
  if (isRenderBlocked.value) {
    ElMessage.warning("推理任务仍在运行，当前版本暂时不可导出");
    return;
  }

  isExporting.value = true;
  progress.value = 0;
  statusMessage.value = "准备导出...";
  resultFiles.value = [];
  stopTracking();

  try {
    const payload = {
      document_version: documentVersion.value,
      target_dir: targetDir.value.trim(),
    };

    const jobResp =
      exportType.value === "composition"
        ? await exportComposition(payload)
        : await exportSegments(payload);

    trackExportJob(jobResp);
    trackJob(jobResp.export_job_id);
  } catch (err: any) {
    ElMessage.error(
      err?.response?.data?.detail || err.message || "启动导出失败",
    );
    isExporting.value = false;
  }
}

function stopTracking() {
  if (unsubscribe) {
    unsubscribe();
    unsubscribe = null;
  }
  if (pollingIntervalId) {
    clearInterval(pollingIntervalId);
    pollingIntervalId = null;
  }
}

function applyJobState(job: ExportJobResponse) {
  progress.value = Math.round((job.progress ?? 0) * 100);
  statusMessage.value =
    job.message || (job.status === "completed" ? "导出完成" : "正在导出...");

  if (job.status === "failed") {
    stopTracking();
    isExporting.value = false;
    ElMessage.error(job.message || "导出失败");
    return;
  }

  if (job.status !== "completed") {
    return;
  }

  stopTracking();
  statusMessage.value = "导出完成";
  progress.value = 100;
  if (job.output_manifest) {
    if (job.output_manifest.composition_file) {
      resultFiles.value = [job.output_manifest.composition_file];
    } else {
      resultFiles.value = job.output_manifest.segment_files || [];
    }
  }
  isExporting.value = false;
  ElMessage.success("导出成功");
}

async function pollExportJob(jobId: string) {
  try {
    const job = await getExportJob(jobId);
    applyJobState(job);
  } catch (err: any) {
    stopTracking();
    statusMessage.value = err?.message || "导出状态查询失败";
    isExporting.value = false;
    ElMessage.error(statusMessage.value);
  }
}

function startPolling(jobId: string) {
  if (pollingIntervalId) {
    return;
  }
  void pollExportJob(jobId);
  pollingIntervalId = setInterval(() => {
    void pollExportJob(jobId);
  }, 2000);
}

function trackJob(jobId: string) {
  stopTracking();
  unsubscribe = subscribeExportJobEvents(jobId, {
    onStateChanged(job) {
      applyJobState(job);
    },
    onProgress(p, msg) {
      progress.value = p * 100;
      statusMessage.value = msg;
    },
    onCompleted(job: ExportJobResponse) {
      applyJobState(job);
    },
    onError() {
      statusMessage.value = "事件流断开，正在改用轮询继续跟踪...";
      startPolling(jobId);
    },
  });
}

async function handleSelectFolder() {
  try {
    const selected = await openFolderDialog(targetDir.value);
    if (selected) {
      targetDir.value = selected;
    }
  } catch (err: any) {
    if (extractStatusCode(err) === 404) {
      ElMessage.warning("当前后端未提供目录选择接口，请直接手动输入导出目录");
      return;
    }
    ElMessage.error(err?.message || "选择目录失败");
  }
}

function closeDialog() {
  if (isExporting.value) {
    ElMessage.warning("正在导出中，请稍候");
    return;
  }
  stopTracking();
  emit("update:visible", false);
}

onBeforeUnmount(() => {
  stopTracking();
});
</script>

<template>
  <el-dialog
    :lock-scroll="false"
    :model-value="visible"
    @update:model-value="emit('update:visible', $event)"
    title="导出音频"
    width="500px"
    top="15vh"
    :close-on-click-modal="false"
    :show-close="!isExporting"
    destroy-on-close
    @close="closeDialog"
  >
    <div class="flex w-full flex-col gap-5 px-1 py-1">
      <div>
        <label class="mb-2 block text-sm font-medium text-foreground/90"
          >导出类型</label
        >
        <el-radio-group v-model="exportType" :disabled="isExporting">
          <el-radio-button value="composition">整条导出</el-radio-button>
          <el-radio-button value="segments">分段导出</el-radio-button>
        </el-radio-group>
      </div>

      <div>
        <label class="mb-2 block text-sm font-medium text-foreground/90"
          >导出根目录（绝对路径）</label
        >
        <div class="flex gap-2">
          <el-input
            v-model="targetDir"
            placeholder="请选择导出根目录..."
            :disabled="isExporting"
          />
          <el-button @click="handleSelectFolder" :disabled="isExporting"
            >选择目录</el-button
          >
        </div>
        <p class="mt-2 text-xs leading-5 text-muted-fg">
          整条导出会直接写入该目录，并命名为 `neo-tts-export-时间戳.wav`；
          分段导出会自动创建 `neo-tts-export-时间戳` 文件夹，内部文件命名为
          `segments-N.wav`。
        </p>
      </div>

      <div
        v-if="isExporting || Math.round(progress) > 0"
        class="space-y-2 mt-2"
      >
        <div class="flex justify-between text-xs text-muted-fg">
          <span>{{ statusMessage }}</span>
          <span>{{ Math.round(progress) }}%</span>
        </div>
        <el-progress :percentage="progress" :show-text="false" />
      </div>

      <div
        v-if="!isExporting && resultFiles.length > 0"
        class="mt-2 rounded-lg border border-green-500/30 bg-green-500/10 p-3"
      >
        <div class="text-sm font-medium text-green-600 text-center">
          成功导出 {{ resultFiles.length }} 条音频
        </div>
      </div>
    </div>

    <template #footer>
      <div class="flex justify-end gap-2">
        <el-button @click="closeDialog" :disabled="isExporting">取消</el-button>
        <el-button
          type="primary"
          @click="startExport"
          :loading="isExporting"
          :disabled="isExporting || !canStartExport"
        >
          {{ footerButtonLabel }}
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>
