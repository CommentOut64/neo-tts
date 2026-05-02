import axios from './http'

import type {
  BindingCatalogResponse,
  CreateRegistryWorkspacePayload,
  TtsRegistryAdapterDefinition,
  TtsRegistryFamilyDefinition,
  TtsRegistryWorkspaceSummary,
  TtsRegistryWorkspaceTree,
} from '@/types/ttsRegistry'

export async function fetchRegistryAdapters(): Promise<TtsRegistryAdapterDefinition[]> {
  const { data } = await axios.get<TtsRegistryAdapterDefinition[]>('/v1/tts-registry/adapters')
  return data
}

export async function fetchRegistryWorkspaces(): Promise<TtsRegistryWorkspaceSummary[]> {
  const { data } = await axios.get<TtsRegistryWorkspaceSummary[]>('/v1/tts-registry/workspaces')
  return data
}

export async function fetchAdapterFamilies(adapterId: string): Promise<TtsRegistryFamilyDefinition[]> {
  const { data } = await axios.get<TtsRegistryFamilyDefinition[]>(`/v1/tts-registry/adapters/${adapterId}/families`)
  return data
}

export async function createRegistryWorkspace(
  payload: CreateRegistryWorkspacePayload,
): Promise<TtsRegistryWorkspaceSummary> {
  const { data } = await axios.post<TtsRegistryWorkspaceSummary>('/v1/tts-registry/workspaces', payload)
  return data
}

export async function fetchBindingCatalog(): Promise<BindingCatalogResponse> {
  const { data } = await axios.get<BindingCatalogResponse>('/v1/tts-registry/bindings/catalog')
  return data
}

export async function fetchRegistryWorkspaceTree(workspaceId: string): Promise<TtsRegistryWorkspaceTree> {
  const { data } = await axios.get<TtsRegistryWorkspaceTree>(`/v1/tts-registry/workspaces/${workspaceId}`)
  return data
}
