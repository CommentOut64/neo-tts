export interface VoiceDefaults {
  speed: number
  top_k: number
  top_p: number
  temperature: number
  noise_scale?: number
  pause_length: number
}

export interface VoiceProfile {
  name: string
  gpt_path: string
  sovits_path: string
  weight_storage_mode: 'external' | 'managed'
  gpt_fingerprint: string
  sovits_fingerprint: string
  ref_audio: string
  ref_text: string
  ref_lang: string
  description: string
  defaults: VoiceDefaults
  managed: boolean
  created_at?: string | null
  updated_at?: string | null
}

export interface InferenceParams {
  speed: number
  temperature: number
  top_p: number
  top_k: number
  noise_scale: number
  pause_length: number
  text_lang: string
  text_split_method: string
  chunk_length: number
}

export type InferenceProgressStatus =
  | 'idle'
  | 'preparing'
  | 'inferencing'
  | 'cancelling'
  | 'completed'
  | 'cancelled'
  | 'error'

export interface InferenceProgressState {
  task_id: string | null
  status: InferenceProgressStatus
  progress: number
  message: string
  cancel_requested: boolean
  current_segment: number | null
  total_segments: number | null
  result_id: string | null
  updated_at: string
}

export interface ForcePauseResponse {
  accepted: boolean
  state: InferenceProgressState
}

export interface CleanupResidualsResponse {
  cancelled_active_task: boolean
  removed_temp_ref_dirs: number
  removed_result_files: number
  state: InferenceProgressState
}

export interface InferenceParamsCacheResponse {
  payload: Record<string, unknown>
  updated_at: string | null
}

export interface ReferenceSelectionByBindingEntry {
  source: 'preset' | 'custom'
  session_reference_asset_id?: string | null
  custom_ref_path: string | null
  ref_text: string
  ref_lang: string
}

export type ReferenceSelectionByBinding = Record<string, ReferenceSelectionByBindingEntry>

export interface InferenceParamsCachePayloadV2 {
  voice_id: string
  speed: number
  temperature: number
  top_p: number
  top_k: number
  noise_scale: number
  pause_length: number
  chunk_length: number
  text_lang: string
  text_split_method: string
  referenceSelectionsByBinding: ReferenceSelectionByBinding
}

export interface InferenceParamsCacheEnvelope {
  payload: Record<string, unknown>
  updatedAt: string | null
}
