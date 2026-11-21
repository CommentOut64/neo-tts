export type ProjectCapability = {
  play: boolean;
  export: boolean;
  edit: boolean;
  render: boolean;
  boundary: boolean;
};

export type ProjectError = {
  code: string;
  phase: string;
  retryable: boolean;
  action: string;
  request_id: string;
  message: string;
};

export type ProjectActionResponse = {
  ok: boolean;
  project_id: string | null;
  workspace_id: string | null;
  workspace_path?: string;
  save_revision: number;
  dirty: boolean;
  last_save_stale?: boolean;
  capability: ProjectCapability;
  project?: Record<string, unknown>;
  error?: ProjectError;
};

export type ProjectPayload = Record<string, unknown>;

export type ProjectCaptureToken = {
  workspace_id: string;
  project_id: string;
  head_revision?: number;
  baseline_revision?: number;
  timeline_revision?: number;
  checkpoint_partial_revision?: number;
  checkpoint_working_revision?: number;
  draft_revision?: number;
  input_revision?: number;
  reference_hashes?: Record<string, string>;
  root_asset_ids?: string[];
  expected_save_revision?: number;
  created_at?: string;
};
