import { computed, ref } from "vue";
import {
  getVersion,
  checkForAppUpdate,
  restartAndApplyAppUpdate,
  startAppUpdateDownload,
} from "@/api/system";
import { ElMessage } from "element-plus";
import type {
  AppUpdateCheckResponse,
  AppUpdateProgress,
  AppUpdateState,
  AppUpdateStatus,
} from "@/types/update";

const ignoredReleaseStorageKey = "neo-tts-ignored-update-release-id";
const downloadPollIntervalMs = 1000;

export function formatVersionLabel(version: string): string {
  return version.startsWith("v") ? version : `v${version}`;
}

export function useAppUpdate() {
  const version = ref("获取中...");
  const isCheckingUpdate = ref(false);
  const updateState = ref<AppUpdateState>({
    status: "idle",
  });
  let downloadPollTimer: ReturnType<typeof setTimeout> | null = null;

  const isUpdateDialogVisible = computed(() =>
    !["idle", "checking", "up-to-date"].includes(updateState.value.status),
  );

  async function fetchVersion() {
    try {
      const res = await getVersion();
      version.value = formatVersionLabel(res.version);
    } catch {
      version.value = "未知";
    }
  }

  async function handleCheckUpdate(silent = false) {
    if (isCheckingUpdate.value) {
      return;
    }

    isCheckingUpdate.value = true;
    updateState.value = {
      status: "checking",
    };

    try {
      const response = await checkForAppUpdate({
        channel: "stable",
        automatic: silent,
      });
      clearDownloadPollTimer(downloadPollTimer);
      downloadPollTimer = null;

      if (shouldSuppressIgnoredRelease(response)) {
        updateState.value = { status: "idle" };
        return;
      }

      updateState.value = stateFromCheckResponse(response);
      if (
        updateState.value.status === "downloading" &&
        typeof updateState.value.releaseId === "string" &&
        updateState.value.releaseId.length > 0
      ) {
        scheduleDownloadPoll(updateState.value.releaseId);
      }

      if (response.status === "up-to-date" && !silent) {
        ElMessage.success("当前已是最新版本");
      }
    } catch (error) {
      const errorMessage = extractErrorMessage(error);
      updateState.value = {
        status: "error",
        errorMessage,
      };
      if (!silent) {
        ElMessage.error(`检查更新失败: ${errorMessage}`);
      }
    } finally {
      isCheckingUpdate.value = false;
    }
  }

  async function startUpdateDownload() {
    const releaseId = updateState.value.releaseId;
    if (!releaseId) {
      return;
    }

    const previousState = updateState.value;
    updateState.value = {
      ...previousState,
      status: "downloading",
      progress: previousState.progress,
    };

    try {
      const response = await startAppUpdateDownload({ releaseId });
      updateState.value = stateFromPartialResponse(previousState, response.status, {
        releaseId: response.releaseId ?? releaseId,
        progress: response.progress,
        errorCode: response.errorCode,
        errorMessage: response.message,
      });
      if (updateState.value.status === "downloading") {
        scheduleDownloadPoll(releaseId);
      }
    } catch (error) {
      const errorMessage = extractErrorMessage(error);
      updateState.value = {
        ...previousState,
        status: "error",
        errorMessage,
      };
      ElMessage.error(`下载更新失败: ${errorMessage}`);
    }
  }

  async function restartAndApplyUpdate() {
    const releaseId = updateState.value.releaseId;
    if (!releaseId) {
      return;
    }

    const previousState = updateState.value;
    try {
      const response = await restartAndApplyAppUpdate({ releaseId });
      updateState.value = {
        ...previousState,
        status: normalizeStatus(response.status, "switching"),
      };
    } catch (error) {
      const errorMessage = extractErrorMessage(error);
      updateState.value = {
        ...previousState,
        status: "error",
        errorMessage,
      };
      ElMessage.error(`重启更新失败: ${errorMessage}`);
    }
  }

  function ignoreUpdate() {
    if (typeof updateState.value.releaseId === "string" && updateState.value.releaseId.length > 0) {
      writeIgnoredReleaseId(updateState.value.releaseId);
    }
    clearDownloadPollTimer(downloadPollTimer);
    downloadPollTimer = null;
    updateState.value = { status: "idle" };
  }

  function dismissUpdateDialog() {
    if (updateState.value.status === "switching") {
      return;
    }
    clearDownloadPollTimer(downloadPollTimer);
    downloadPollTimer = null;
    updateState.value = { status: "idle" };
  }

  function scheduleDownloadPoll(releaseId: string) {
    clearDownloadPollTimer(downloadPollTimer);
    downloadPollTimer = setTimeout(() => {
      void pollDownloadProgress(releaseId);
    }, downloadPollIntervalMs);
  }

  async function pollDownloadProgress(releaseId: string) {
    try {
      const response = await checkForAppUpdate({
        channel: "stable",
        automatic: true,
      });
      updateState.value = stateFromCheckResponse(response, updateState.value);
      if (updateState.value.status === "downloading" && updateState.value.releaseId === releaseId) {
        scheduleDownloadPoll(releaseId);
        return;
      }
      clearDownloadPollTimer(downloadPollTimer);
      downloadPollTimer = null;
    } catch (error) {
      const errorMessage = extractErrorMessage(error);
      updateState.value = {
        ...updateState.value,
        status: "error",
        errorMessage,
      };
      clearDownloadPollTimer(downloadPollTimer);
      downloadPollTimer = null;
    }
  }

  return {
    version,
    isCheckingUpdate,
    updateState,
    isUpdateDialogVisible,
    fetchVersion,
    handleCheckUpdate,
    startUpdateDownload,
    restartAndApplyUpdate,
    ignoreUpdate,
    dismissUpdateDialog,
  };
}

function stateFromCheckResponse(
  response: AppUpdateCheckResponse,
  previousState: AppUpdateState = { status: "idle" },
): AppUpdateState {
  return {
    ...previousState,
    status: normalizeStatus(response.status, "error"),
    releaseId: response.releaseId ?? previousState.releaseId,
    notesUrl: response.notesUrl ?? previousState.notesUrl,
    changedPackages: response.changedPackages ?? previousState.changedPackages,
    estimatedDownloadBytes:
      response.estimatedDownloadBytes ?? previousState.estimatedDownloadBytes,
    minBootstrapVersion: response.minBootstrapVersion ?? previousState.minBootstrapVersion,
    progress: response.progress ?? previousState.progress,
    errorCode: response.errorCode,
    errorMessage: response.errorMessage,
  };
}

function stateFromPartialResponse(
  previousState: AppUpdateState,
  status: string,
  options: {
    releaseId?: string;
    progress?: AppUpdateProgress;
    errorCode?: string;
    errorMessage?: string;
  },
): AppUpdateState {
  return {
    ...previousState,
    status: normalizeStatus(status, "error"),
    releaseId: options.releaseId ?? previousState.releaseId,
    progress: options.progress ?? previousState.progress,
    errorCode: options.errorCode,
    errorMessage: options.errorMessage,
  };
}

function shouldSuppressIgnoredRelease(response: AppUpdateCheckResponse): boolean {
  return (
    response.status === "update-available" &&
    typeof response.releaseId === "string" &&
    response.releaseId.length > 0 &&
    response.releaseId === readIgnoredReleaseId()
  );
}

function normalizeStatus(status: string, fallback: AppUpdateStatus): AppUpdateStatus {
  switch (status) {
    case "idle":
    case "checking":
    case "up-to-date":
    case "update-available":
    case "bootstrap-upgrade-required":
    case "downloading":
    case "ready-to-restart":
    case "switching":
    case "error":
      return status;
    default:
      return fallback;
  }
}

function clearDownloadPollTimer(timer: ReturnType<typeof setTimeout> | null) {
  if (timer !== null) {
    clearTimeout(timer);
  }
}

function readIgnoredReleaseId(): string | null {
  if (typeof localStorage === "undefined") {
    return null;
  }
  try {
    return localStorage.getItem(ignoredReleaseStorageKey);
  } catch {
    return null;
  }
}

function writeIgnoredReleaseId(releaseId: string): void {
  if (typeof localStorage === "undefined") {
    return;
  }
  try {
    localStorage.setItem(ignoredReleaseStorageKey, releaseId);
  } catch {
    // 本地存储失败不影响当前 UI 状态。
  }
}

function extractErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim().length > 0) {
    return error.message;
  }
  return "网络错误";
}
