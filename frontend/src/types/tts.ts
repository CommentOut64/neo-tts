export interface VoiceDefaults {
  speed: number
  top_k: number
  top_p: number
  temperature: number
  pause_length: number
}

export interface VoiceProfile {
  name: string
  gpt_path: string
  sovits_path: string
  ref_audio: string
  ref_text: string
  ref_lang: string
  description: string
  defaults: VoiceDefaults
  managed: boolean
  created_at?: string | null
  updated_at?: string | null
}

export interface AudioHistoryItem {
  id: string
  text: string
  blobUrl: string | null
  duration: number | null
  createdAt: Date
  status: 'pending' | 'done' | 'error'
  errorMessage?: string
}

export interface InferenceParams {
  speed: number
  temperature: number
  top_p: number
  top_k: number
  pause_length: number
  text_lang: string
  chunk_length: number
}

export interface SpeechRequest {
  input: string
  voice: string
  model?: string
  response_format?: string
  speed?: number
  top_k?: number
  top_p?: number
  temperature?: number
  text_lang?: string
  chunk_length?: number
  history_window?: number
  pause_length?: number
  noise_scale?: number
  sid?: number
  ref_audio?: string
  ref_audio_file?: File
  ref_text?: string
  ref_lang?: string
}
