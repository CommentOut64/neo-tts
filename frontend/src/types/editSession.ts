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

export interface EditableSegment {
  segment_id: string
  document_id: string
  order_key: number
  previous_segment_id: string | null
  next_segment_id: string | null
  segment_kind: 'speech'
  raw_text: string
  normalized_text: string
  text_language: string
  render_version: number
  render_asset_id: string | null
  group_id: string | null
  render_profile_id: string | null
  voice_binding_id: string | null
  render_status: 'pending' | 'rendering' | 'ready' | 'paused' | 'failed'
  segment_revision: number
  effective_duration_samples: number | null
  inference_override: Record<string, unknown>
  risk_flags: string[]
  assembled_audio_span: [number, number] | null
}

export interface SegmentListResponse {
  document_id: string
  document_version: number
  items: EditableSegment[]
  next_cursor: number | null
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

export interface TimelineBlockEntry {
  block_asset_id: string;
  segment_ids: string[];
  start_sample: number;
  end_sample: number;
  audio_sample_count: number;
  audio_url: string;
}

export interface TimelineSegmentEntry {
  segment_id: string;
  order_key: number;
  start_sample: number;
  end_sample: number;
  render_status: string;
  group_id: string | null;
  render_profile_id: string | null;
  voice_binding_id: string | null;
}

export interface TimelineEdgeEntry {
  edge_id: string;
  left_segment_id: string;
  right_segment_id: string;
  pause_duration_seconds: number;
  boundary_strategy: string;
  effective_boundary_strategy: string;
  boundary_start_sample: number;
  boundary_end_sample: number;
  pause_start_sample: number;
  pause_end_sample: number;
}

export interface TimelineMarkerEntry {
  marker_id: string;
  marker_type:
    | "segment_start"
    | "segment_end"
    | "edge_gap_start"
    | "edge_gap_end"
    | "block_start"
    | "block_end";
  sample: number;
  related_id: string;
}

export interface TimelineManifest {
  timeline_version: number;
  sample_rate: number;
  total_samples: number;
  block_entries: TimelineBlockEntry[];
  segment_entries: TimelineSegmentEntry[];
  edge_entries: TimelineEdgeEntry[];
  markers: TimelineMarkerEntry[];
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
