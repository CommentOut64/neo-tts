import axios from './http'
import type { VoiceProfile } from '@/types/tts'

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

export async function uploadVoice(params: {
  name: string
  description?: string
  ref_text: string
  ref_lang?: string
  speed?: number
  top_k?: number
  top_p?: number
  temperature?: number
  pause_length?: number
  gpt_file: File
  sovits_file: File
  ref_audio_file: File
}): Promise<VoiceProfile> {
  const form = new FormData()
  form.append('name', params.name)
  form.append('description', params.description ?? '')
  form.append('ref_text', params.ref_text)
  form.append('ref_lang', params.ref_lang ?? 'zh')
  if (params.speed !== undefined) form.append('speed', String(params.speed))
  if (params.top_k !== undefined) form.append('top_k', String(params.top_k))
  if (params.top_p !== undefined) form.append('top_p', String(params.top_p))
  if (params.temperature !== undefined) form.append('temperature', String(params.temperature))
  if (params.pause_length !== undefined) form.append('pause_length', String(params.pause_length))
  form.append('gpt_file', params.gpt_file)
  form.append('sovits_file', params.sovits_file)
  form.append('ref_audio_file', params.ref_audio_file)
  const { data } = await axios.post<VoiceProfile>('/v1/voices/upload', form)
  return data
}

export async function deleteVoice(name: string): Promise<{ status: string; name: string }> {
  const { data } = await axios.delete<{ status: string; name: string }>(`/v1/voices/${name}`)
  return data
}
