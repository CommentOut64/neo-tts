export interface PrepareExitResponse {
  status: "prepared";
  launcher_exit_requested: boolean;
  active_render_job_status: string | null;
  inference_status: string;
}

export type ExitChoice =
  | "continue_editing"
  | "save_and_exit"
  | "discard_and_exit";
