import axios from './http'
import type { VoiceProfile } from '@/types/tts'

type UploadVoiceParams = {
  name: string
  description?: string
  copy_weights_into_project: boolean
  ref_text: string
  ref_lang?: string
  speed?: number
  top_k?: number
  top_p?: number
  temperature?: number
  noise_scale?: number
  pause_length?: number
  gpt_external_path?: string
  sovits_external_path?: string
  gpt_file?: File | null
  sovits_file?: File | null
  ref_audio_file: File
}

export type UpdateVoiceParams = {
  description?: string
  copy_weights_into_project?: boolean
  ref_text?: string
  ref_lang?: string
  gpt_external_path?: string
  sovits_external_path?: string
  gpt_file?: File | null
  sovits_file?: File | null
  ref_audio_file?: File | null
}

export async function fetchVoices(): Promise<VoiceProfile[]> {
  const { data } = await axios.get<VoiceProfile[]>('/v1/voices')
  return data
}

export async function fetchVoiceDetail(name: string): Promise<VoiceProfile> {
  const { data } = await axios.get<VoiceProfile>(`/v1/voices/${name}`)
  return data
}

export async function reloadVoices(): Promise<{ status: string; count: number }> {
  const { data } = await axios.post<{ status: string; count: number }>('/v1/voices/reload')
  return data
}

function buildUploadVoiceFormData(params: UploadVoiceParams): FormData {
  const form = new FormData()
  form.append('name', params.name)
  form.append('description', params.description ?? '')
  form.append('copy_weights_into_project', String(params.copy_weights_into_project))
  form.append('ref_text', params.ref_text)
  form.append('ref_lang', params.ref_lang ?? 'zh')
  if (params.speed !== undefined) form.append('speed', String(params.speed))
  if (params.top_k !== undefined) form.append('top_k', String(params.top_k))
  if (params.top_p !== undefined) form.append('top_p', String(params.top_p))
  if (params.temperature !== undefined) form.append('temperature', String(params.temperature))
  if (params.noise_scale !== undefined) form.append('noise_scale', String(params.noise_scale))
  if (params.pause_length !== undefined) form.append('pause_length', String(params.pause_length))
  if (params.gpt_external_path) form.append('gpt_external_path', params.gpt_external_path)
  if (params.sovits_external_path) form.append('sovits_external_path', params.sovits_external_path)
  if (params.gpt_file) form.append('gpt_file', params.gpt_file)
  if (params.sovits_file) form.append('sovits_file', params.sovits_file)
  form.append('ref_audio_file', params.ref_audio_file)
  return form
}

export function buildUpdateVoiceFormData(params: UpdateVoiceParams): FormData {
  const form = new FormData()
  if (params.description !== undefined) form.append('description', params.description)
  if (params.copy_weights_into_project !== undefined) {
    form.append('copy_weights_into_project', String(params.copy_weights_into_project))
  }
  if (params.ref_text !== undefined) form.append('ref_text', params.ref_text)
  if (params.ref_lang !== undefined) form.append('ref_lang', params.ref_lang)
  if (params.gpt_external_path) form.append('gpt_external_path', params.gpt_external_path)
  if (params.sovits_external_path) form.append('sovits_external_path', params.sovits_external_path)
  if (params.gpt_file) form.append('gpt_file', params.gpt_file)
  if (params.sovits_file) form.append('sovits_file', params.sovits_file)
  if (params.ref_audio_file) form.append('ref_audio_file', params.ref_audio_file)
  return form
}

export async function uploadVoice(params: UploadVoiceParams): Promise<VoiceProfile> {
  const form = buildUploadVoiceFormData(params)
  const { data } = await axios.post<VoiceProfile>('/v1/voices/upload', form)
  return data
}

export async function updateVoice(name: string, params: UpdateVoiceParams): Promise<VoiceProfile> {
  const form = buildUpdateVoiceFormData(params)
  const { data } = await axios.patch<VoiceProfile>(`/v1/voices/${name}`, form)
  return data
}

export async function deleteVoice(name: string): Promise<{ status: string; name: string }> {
  const { data } = await axios.delete<{ status: string; name: string }>(`/v1/voices/${name}`)
  return data
}
