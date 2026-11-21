import { computed, ref } from "vue";
import {
  createProject,
  importLegacyProject,
  openProject,
  saveProject,
  saveProjectAs,
} from "@/api/projects";
import { ApiRequestError } from "@/api/requestSupport";
import type {
  ProjectActionResponse,
  ProjectCapability,
  ProjectCaptureToken,
  ProjectError,
  ProjectPayload,
} from "@/types/projects";

type CaptureSource = () => ProjectPayload | Promise<ProjectPayload>;
type RestoreHandler = (project: Record<string, unknown> | undefined) => void | Promise<void>;

const DEFAULT_CAPABILITY: ProjectCapability = {
  play: true,
  export: true,
  edit: true,
  render: true,
  boundary: true,
};

function errorFromUnknown(error: unknown): ProjectError {
  if (error instanceof ApiRequestError && error.projectError) {
    const raw = error.projectError;
    return {
      code: typeof raw.code === "string" ? raw.code : "PROJECT_REQUEST_FAILED",
      phase: typeof raw.phase === "string" ? raw.phase : "transport",
      retryable: raw.retryable === true,
      action: typeof raw.action === "string" ? raw.action : "retry",
      request_id: typeof raw.request_id === "string" ? raw.request_id : "",
      message: typeof raw.message === "string" ? raw.message : error.message,
    };
  }
  return {
    code: "PROJECT_REQUEST_FAILED",
    phase: "transport",
    retryable: false,
    action: "retry",
    request_id: "",
    message: error instanceof Error ? error.message : String(error),
  };
}

function buildCaptureToken(
  payload: ProjectPayload,
  workspaceId: string | null,
  expectedSaveRevision: number,
): ProjectCaptureToken | undefined {
  const rawProject = payload.project;
  if (!rawProject || typeof rawProject !== "object" || Array.isArray(rawProject)) {
    return undefined;
  }
  const project = rawProject as Record<string, unknown>;
  const projectId = project.project_id;
  if (typeof projectId !== "string" || !workspaceId) {
    return undefined;
  }
  const numberOrZero = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? value : 0;
  const rootAssetIds = Array.isArray(payload.assets)
    ? payload.assets
        .filter((item): item is Record<string, unknown> => !!item && typeof item === "object" && !Array.isArray(item))
        .map((item) => item.asset_id)
        .filter((item): item is string => typeof item === "string")
    : [];
  const referenceHashes = project.reference_hashes && typeof project.reference_hashes === "object"
    && !Array.isArray(project.reference_hashes)
    ? Object.fromEntries(
        Object.entries(project.reference_hashes as Record<string, unknown>).filter(
          ([key, value]): value is string => typeof key === "string" && typeof value === "string",
        ),
      )
    : {};
  return {
    workspace_id: workspaceId,
    project_id: projectId,
    head_revision: numberOrZero(project.head_revision),
    baseline_revision: numberOrZero(project.baseline_revision),
    timeline_revision: numberOrZero(project.timeline_revision),
    checkpoint_partial_revision: numberOrZero(project.checkpoint_partial_revision),
    checkpoint_working_revision: numberOrZero(project.checkpoint_working_revision),
    draft_revision: numberOrZero(project.draft_revision),
    input_revision: numberOrZero(project.input_revision),
    root_asset_ids: rootAssetIds,
    reference_hashes: referenceHashes,
    expected_save_revision: expectedSaveRevision,
    created_at: new Date().toISOString(),
  };
}

export function useProjectLifecycle(options: {
  capture?: CaptureSource;
  restore?: RestoreHandler;
  flushDraft?: () => void | Promise<void>;
} = {}) {
  const projectId = ref<string | null>(null);
  const workspaceId = ref<string | null>(null);
  const saveRevision = ref(0);
  const dirty = ref(false);
  const readOnly = ref(false);
  const capability = ref<ProjectCapability>({ ...DEFAULT_CAPABILITY });
  const lastError = ref<ProjectError | null>(null);
  const isBusy = ref(false);
  let captureSource = options.capture;
  let restoreHandler = options.restore;

  function installCaptureSource(next: CaptureSource): void {
    captureSource = next;
  }

  function installRestoreHandler(next: RestoreHandler): void {
    restoreHandler = next;
  }

  function applyResponse(response: ProjectActionResponse): void {
    projectId.value = response.project_id;
    workspaceId.value = response.workspace_id;
    saveRevision.value = response.save_revision;
    dirty.value = response.dirty;
    capability.value = response.capability ?? { ...DEFAULT_CAPABILITY };
    readOnly.value = !capability.value.edit;
    lastError.value = response.error ?? null;
  }

  async function restoreResponse(response: ProjectActionResponse): Promise<ProjectActionResponse> {
    applyResponse(response);
    await restoreHandler?.(response.project);
    return response;
  }

  async function runAction(action: () => Promise<ProjectActionResponse>): Promise<ProjectActionResponse | null> {
    if (isBusy.value) {
      return null;
    }
    isBusy.value = true;
    lastError.value = null;
    try {
      return await action();
    } catch (error) {
      // A failed save/open must not clear the current session or dirty flag.
      lastError.value = errorFromUnknown(error);
      return null;
    } finally {
      isBusy.value = false;
    }
  }

  async function createNew(input: { project_id?: string; workspace_id?: string } = {}) {
    const response = await runAction(() => createProject(input));
    return response ? restoreResponse(response) : null;
  }

  async function open(path: string) {
    if (!path.trim()) {
      lastError.value = errorFromUnknown(new Error("请选择 .neo 项目文件"));
      return null;
    }
    const response = await runAction(() => openProject(path));
    return response ? restoreResponse(response) : null;
  }

  async function save(token?: ProjectCaptureToken) {
    if (!captureSource) {
      lastError.value = errorFromUnknown(new Error("项目捕获源尚未安装"));
      return null;
    }
    if (readOnly.value) {
      lastError.value = errorFromUnknown(new Error("当前项目为只读降级状态"));
      return null;
    }
    const response = await runAction(async () => {
      await options.flushDraft?.();
      const captured = await captureSource!();
      const captureToken = token ?? buildCaptureToken(captured, workspaceId.value, saveRevision.value);
      return saveProject(captured, captureToken);
    });
    if (response) {
      applyResponse(response);
    }
    return response;
  }

  async function saveAs(target: string, token?: ProjectCaptureToken) {
    if (!target.trim()) {
      lastError.value = errorFromUnknown(new Error("请选择另存为目标路径"));
      return null;
    }
    if (!captureSource) {
      lastError.value = errorFromUnknown(new Error("项目捕获源尚未安装"));
      return null;
    }
    const response = await runAction(async () => {
      await options.flushDraft?.();
      return saveProjectAs(await captureSource!(), target, token);
    });
    if (response) {
      applyResponse(response);
    }
    return response;
  }

  async function importLegacy(path: string, importedProjectId?: string) {
    const response = await runAction(() => importLegacyProject(path, importedProjectId));
    return response ? restoreResponse(response) : null;
  }

  function markDirty(next = true): void {
    dirty.value = next;
  }

  function close(): void {
    projectId.value = null;
    workspaceId.value = null;
    saveRevision.value = 0;
    dirty.value = false;
    readOnly.value = false;
    capability.value = { ...DEFAULT_CAPABILITY };
    lastError.value = null;
  }

  return {
    projectId,
    workspaceId,
    saveRevision,
    dirty,
    readOnly,
    capability: computed(() => capability.value),
    lastError,
    isBusy,
    installCaptureSource,
    installRestoreHandler,
    markDirty,
    close,
    createNew,
    open,
    save,
    saveAs,
    importLegacy,
  };
}
