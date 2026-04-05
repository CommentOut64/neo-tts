export type RenderJobStatus =
  | 'queued' | 'preparing' | 'rendering' | 'composing' | 'committing'
  | 'pause_requested' | 'paused'
  | 'cancel_requested' | 'cancelled_partial'
  | 'completed' | 'failed'

export interface RenderJobSummary {
  job_id: string
  status: RenderJobStatus
  progress: number
  message: string
}

export interface RenderJob extends RenderJobSummary {
  document_id: string
  cancel_requested?: boolean
  pause_requested?: boolean
  current_segment_index?: number | null
  total_segment_count?: number | null
  current_block_index?: number | null
  total_block_count?: number | null
  result_document_version?: number | null
  checkpoint_id?: string | null
  resume_token?: string | null
  updated_at?: string
}

export interface EditSessionSnapshot {
  session_status: 'empty' | 'initializing' | 'ready' | 'failed'
  document_version: number | null
  active_job: RenderJobSummary | null
}

export interface InitializeRequest {
  raw_text: string
  text_language?: string
  voice_id: string
  reference_audio_path?: string
  reference_text?: string
  reference_language?: string
  speed?: number
  temperature?: number
  top_k?: number
  top_p?: number
  pause_duration_seconds?: number
  noise_scale?: number
  segment_boundary_mode?: 'raw_strong_punctuation' | 'zh_period'
}

export interface RenderJobResponse {
  job_id: string
  document_id: string
  status: RenderJobStatus
  progress: number
  message: string
}

export interface RenderJobAcceptedResponse {
  job: RenderJobResponse
}

export interface TimelineManifest {
  timeline_version: number
  sample_rate: number
  total_samples: number
  block_entries: any[]
  segment_entries: any[]
  edge_entries: any[]
  markers: any[]
}

export type RenderJobEventType =
  | 'job_state_changed'
  | 'segments_initialized'
  | 'segment_completed'
  | 'block_completed'
  | 'timeline_committed'
  | 'job_paused'
  | 'job_resumed'
  | 'job_cancelled_partial'
  | 'job_completed'
  | 'job_failed'

export interface SegmentsInitializedPayload {
  document_id: string
  document_version: number
  segments: Array<{
    segment_id: string
    order_key: number
    raw_text: string
    render_status: string
  }>
}

export interface SegmentCompletedPayload {
  segment_id: string
  order_key: number
  render_asset_id: string
  render_status: string
  effective_duration_samples: number | null
}

export interface ProgressiveSegment {
  segmentId: string
  orderKey: number
  rawText: string
  renderStatus: 'pending' | 'completed'
  renderAssetId: string | null
}
