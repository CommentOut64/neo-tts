export type RenderJobStatus =
  | 'queued' | 'preparing' | 'rendering' | 'composing' | 'committing'
  | 'pause_requested' | 'paused'
  | 'cancel_requested' | 'cancelled_partial'
  | 'completed' | 'failed'

export interface RenderJobSummary {
  job_id: string
  status: RenderJobStatus
  progress: number
  message: string | null
}

export interface EditSessionSnapshot {
  session_status: 'empty' | 'initializing' | 'ready' | 'failed'
  document_version: number | null
  active_job: RenderJobSummary | null
}
