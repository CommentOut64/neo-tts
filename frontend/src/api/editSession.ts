import axios from './http'
import type { EditSessionSnapshot } from '@/types/editSession'

export async function getSnapshot(): Promise<EditSessionSnapshot> {
  const { data } = await axios.get<EditSessionSnapshot>('/v1/edit-session/snapshot')
  return data
}
