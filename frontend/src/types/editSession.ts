export type RenderJobStatus =
  | 'queued' | 'preparing' | 'rendering' | 'composing' | 'committing'
  | 'pause_requested' | 'paused'
  | 'cancel_requested' | 'cancelled_partial'
  | 'completed' | 'failed'

export interface RenderJobCommitMetadata {
  committed_document_version?: number | null
  committed_timeline_manifest_id?: string | null
  committed_playable_sample_span?: [number, number] | null
  changed_block_asset_ids?: string[]
}

export interface RenderJobSummary extends RenderJobCommitMetadata {
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
  document_id: string | null
  document_version: number | null
  source_text?: string | null
  total_segment_count: number
  total_edge_count?: number
  active_job: RenderJobSummary | null
  default_render_profile_id?: string | null
  default_voice_binding_id?: string | null
  segments: EditableSegment[]
  edges?: EditableEdge[]
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
  terminal_raw?: string
  terminal_closer_suffix?: string
  terminal_source?: 'original' | 'synthetic'
  detected_language?: ResolvedLanguage | null
  inference_exclusion_reason?: InferenceExclusionReason | null
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

export interface EditableEdge {
  edge_id: string
  document_id: string
  left_segment_id: string
  right_segment_id: string
  pause_duration_seconds: number
  boundary_strategy: string
  boundary_strategy_locked?: boolean
  effective_boundary_strategy: string | null
  pause_sample_count: number | null
  boundary_sample_count: number | null
  edge_status: 'pending' | 'rendering' | 'ready' | 'failed'
  edge_version: number
}

export interface SegmentGroup {
  group_id: string
  name: string
  segment_ids: string[]
  render_profile_id: string | null
  voice_binding_id: string | null
  created_by: 'append' | 'batch_patch' | 'manual'
}

export interface RenderProfile {
  render_profile_id: string
  scope: 'session' | 'group' | 'segment'
  name: string
  speed: number
  top_k: number
  top_p: number
  temperature: number
  noise_scale: number
  reference_audio_path: string | null
  reference_text: string | null
  reference_language: string | null
  extra_overrides: Record<string, unknown>
}

export interface VoiceBinding {
  voice_binding_id: string
  scope: 'session' | 'group' | 'segment'
  voice_id: string
  model_key: string
  sovits_path: string | null
  gpt_path: string | null
  speaker_meta: Record<string, unknown>
}

export interface SegmentListResponse {
  document_id: string
  document_version: number
  items: EditableSegment[]
  next_cursor: number | null
}

export interface EdgeListResponse {
  document_id: string
  document_version: number
  items: EditableEdge[]
  next_cursor: number | null
}

export interface GroupListResponse {
  document_id: string
  document_version: number
  items: SegmentGroup[]
}

export interface RenderProfileListResponse {
  document_id: string
  document_version: number
  items: RenderProfile[]
}

export interface VoiceBindingListResponse {
  document_id: string
  document_version: number
  items: VoiceBinding[]
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

export type ResolvedLanguage = 'zh' | 'ja' | 'en' | 'unknown'
export type InferenceExclusionReason =
  | 'none'
  | 'other_language_segment'
  | 'unsupported_language'
  | 'language_unresolved'

export interface StandardizationPreviewRequest {
  raw_text: string
  text_language: 'auto' | 'zh' | 'ja' | 'en'
  request_id?: string
  segment_limit?: number
  cursor?: number | null
  include_language_analysis?: boolean
}

export interface StandardizationPreviewSegment {
  order_key: number
  canonical_text: string
  terminal_raw: string
  terminal_closer_suffix: string
  terminal_source: 'original' | 'synthetic'
  detected_language: ResolvedLanguage | null
  inference_exclusion_reason: InferenceExclusionReason | null
  warnings: string[]
}

export interface StandardizationPreviewResponse {
  analysis_stage: 'light' | 'complete'
  document_char_count: number
  total_segments: number
  next_cursor: number | null
  resolved_document_language: ResolvedLanguage | null
  language_detection_source: 'explicit' | 'auto' | null
  warnings: string[]
  segments: StandardizationPreviewSegment[]
}

export interface ReferenceAudioUploadResponse {
  reference_audio_path: string
  filename: string
}

export interface ConfigurationCommitResponse {
  document_id: string
  document_version: number
  head_snapshot_id: string
}

export interface RenderProfilePatch {
  name?: string | null
  speed?: number | null
  top_k?: number | null
  top_p?: number | null
  temperature?: number | null
  noise_scale?: number | null
  reference_audio_path?: string | null
  reference_text?: string | null
  reference_language?: string | null
  extra_overrides?: Record<string, unknown> | null
}

export interface VoiceBindingPatch {
  voice_id?: string | null
  model_key?: string | null
  sovits_path?: string | null
  gpt_path?: string | null
  speaker_meta?: Record<string, unknown> | null
}

export interface SegmentBatchRenderProfilePatchBody {
  segment_ids: string[]
  patch: RenderProfilePatch
}

export interface SegmentBatchVoiceBindingPatchBody {
  segment_ids: string[]
  patch: VoiceBindingPatch
}

export interface EdgeUpdateBody {
  pause_duration_seconds?: number | null
  boundary_strategy?: string | null
}

export interface ReorderSegmentsBody {
  base_document_version: number
  ordered_segment_ids: string[]
}

export interface RenderJobResponse {
  job_id: string
  document_id: string
  status: RenderJobStatus
  progress: number
  message: string
  cancel_requested?: boolean
  pause_requested?: boolean
  current_segment_index?: number | null
  total_segment_count?: number | null
  current_block_index?: number | null
  total_block_count?: number | null
  result_document_version?: number | null
  committed_document_version?: number | null
  committed_timeline_manifest_id?: string | null
  committed_playable_sample_span?: [number, number] | null
  changed_block_asset_ids?: string[]
  checkpoint_id?: string | null
  resume_token?: string | null
  updated_at?: string
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
  timeline_manifest_id: string;
  document_id: string;
  document_version: number;
  timeline_version: number;
  sample_rate: number;
  playable_sample_span: [number, number];
  block_entries: TimelineBlockEntry[];
  segment_entries: TimelineSegmentEntry[];
  edge_entries: TimelineEdgeEntry[];
  markers: TimelineMarkerEntry[];
  created_at?: string;
}

export type PlaybackCursorKind =
  | "before_start"
  | "segment"
  | "boundary"
  | "pause"
  | "ended";

export interface PlaybackCursor {
  sample: number;
  kind: PlaybackCursorKind;
  segmentId: string | null;
  edgeId: string | null;
  leftSegmentId: string | null;
  rightSegmentId: string | null;
  spanStartSample: number;
  spanEndSample: number;
  progressInSpan: number;
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

export interface RenderJobCommittedPayload {
  committed_document_version: number
  committed_timeline_manifest_id: string
  committed_playable_sample_span: [number, number] | null
  changed_block_asset_ids: string[]
}

export interface SegmentsInitializedPayload {
  document_id: string
  document_version: number
  segments: Array<{
    segment_id: string
    order_key: number
    raw_text: string
    terminal_raw?: string
    terminal_closer_suffix?: string
    terminal_source?: 'original' | 'synthetic'
    detected_language?: ResolvedLanguage | null
    inference_exclusion_reason?: InferenceExclusionReason | null
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
  displayText: string
  renderStatus: 'pending' | 'completed'
  renderAssetId: string | null
}

export interface ExportSegmentsBody {
  document_version: number;
  target_dir: string;
  overwrite_policy?: "fail" | "replace" | "new_folder";
}

export type ExportCompositionBody = ExportSegmentsBody;

export interface ExportOutputManifest {
  export_kind: "segments" | "composition";
  target_dir: string;
  files: string[];
  segment_files: string[];
  composition_file: string | null;
  composition_manifest_id: string | null;
  manifest_file: string;
  exported_at: string;
}

export interface ExportJobResponse {
  export_job_id: string;
  document_id: string;
  document_version: number;
  timeline_manifest_id: string;
  export_kind: "segments" | "composition";
  status: "queued" | "exporting" | "completed" | "failed";
  target_dir: string;
  overwrite_policy: "fail" | "replace" | "new_folder";
  progress: number;
  message: string;
  output_manifest: ExportOutputManifest | null;
  staging_dir: string | null;
  updated_at: string;
}

export interface ExportJobAcceptedResponse {
  job: ExportJobResponse;
}

