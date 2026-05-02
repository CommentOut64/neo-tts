import axios from './http'

import type {
  BindingCatalogResponse,
  CreateRegistryWorkspacePayload,
  CreateRegistryMainModelPayload,
  CreateRegistryPresetPayload,
  CreateRegistrySubmodelPayload,
  PatchRegistryMainModelPayload,
  PatchRegistryPresetPayload,
  PatchRegistrySubmodelPayload,
  PatchRegistryWorkspacePayload,
  PutRegistrySubmodelSecretsPayload,
  TtsRegistryDeleteResult,
  TtsRegistryAdapterDefinition,
  TtsRegistryFamilyDefinition,
  TtsRegistryMainModelRecord,
  TtsRegistryPresetRecord,
  TtsRegistrySubmodelConnectivityCheckResult,
  TtsRegistrySubmodelRecord,
  TtsRegistryWorkspaceRecord,
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

export async function patchRegistryWorkspace(
  workspaceId: string,
  payload: PatchRegistryWorkspacePayload,
): Promise<TtsRegistryWorkspaceRecord> {
  const { data } = await axios.patch<TtsRegistryWorkspaceRecord>(`/v1/tts-registry/workspaces/${workspaceId}`, payload)
  return data
}

export async function deleteRegistryWorkspace(workspaceId: string): Promise<TtsRegistryDeleteResult> {
  const { data } = await axios.delete<TtsRegistryDeleteResult>(`/v1/tts-registry/workspaces/${workspaceId}`)
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

export async function createRegistryMainModel(
  workspaceId: string,
  payload: CreateRegistryMainModelPayload,
): Promise<TtsRegistryMainModelRecord> {
  const { data } = await axios.post<TtsRegistryMainModelRecord>(
    `/v1/tts-registry/workspaces/${workspaceId}/main-models`,
    payload,
  )
  return data
}

export async function patchRegistryMainModel(
  workspaceId: string,
  mainModelId: string,
  payload: PatchRegistryMainModelPayload,
): Promise<TtsRegistryMainModelRecord> {
  const { data } = await axios.patch<TtsRegistryMainModelRecord>(
    `/v1/tts-registry/workspaces/${workspaceId}/main-models/${mainModelId}`,
    payload,
  )
  return data
}

export async function deleteRegistryMainModel(
  workspaceId: string,
  mainModelId: string,
): Promise<TtsRegistryDeleteResult> {
  const { data } = await axios.delete<TtsRegistryDeleteResult>(
    `/v1/tts-registry/workspaces/${workspaceId}/main-models/${mainModelId}`,
  )
  return data
}

export async function createRegistrySubmodel(
  workspaceId: string,
  mainModelId: string,
  payload: CreateRegistrySubmodelPayload,
): Promise<TtsRegistrySubmodelRecord> {
  const { data } = await axios.post<TtsRegistrySubmodelRecord>(
    `/v1/tts-registry/workspaces/${workspaceId}/main-models/${mainModelId}/submodels`,
    payload,
  )
  return data
}

export async function patchRegistrySubmodel(
  workspaceId: string,
  mainModelId: string,
  submodelId: string,
  payload: PatchRegistrySubmodelPayload,
): Promise<TtsRegistrySubmodelRecord> {
  const { data } = await axios.patch<TtsRegistrySubmodelRecord>(
    `/v1/tts-registry/workspaces/${workspaceId}/main-models/${mainModelId}/submodels/${submodelId}`,
    payload,
  )
  return data
}

export async function deleteRegistrySubmodel(
  workspaceId: string,
  mainModelId: string,
  submodelId: string,
): Promise<TtsRegistryDeleteResult> {
  const { data } = await axios.delete<TtsRegistryDeleteResult>(
    `/v1/tts-registry/workspaces/${workspaceId}/main-models/${mainModelId}/submodels/${submodelId}`,
  )
  return data
}

export async function putRegistrySubmodelSecrets(
  workspaceId: string,
  mainModelId: string,
  submodelId: string,
  payload: PutRegistrySubmodelSecretsPayload,
): Promise<TtsRegistrySubmodelRecord> {
  const { data } = await axios.put<TtsRegistrySubmodelRecord>(
    `/v1/tts-registry/workspaces/${workspaceId}/main-models/${mainModelId}/submodels/${submodelId}/secrets`,
    payload,
  )
  return data
}

export async function checkRegistrySubmodelConnectivity(
  workspaceId: string,
  mainModelId: string,
  submodelId: string,
): Promise<TtsRegistrySubmodelConnectivityCheckResult> {
  const { data } = await axios.post<TtsRegistrySubmodelConnectivityCheckResult>(
    `/v1/tts-registry/workspaces/${workspaceId}/main-models/${mainModelId}/submodels/${submodelId}/connectivity-check`,
  )
  return data
}

export async function createRegistryPreset(
  workspaceId: string,
  mainModelId: string,
  submodelId: string,
  payload: CreateRegistryPresetPayload,
): Promise<TtsRegistryPresetRecord> {
  const { data } = await axios.post<TtsRegistryPresetRecord>(
    `/v1/tts-registry/workspaces/${workspaceId}/main-models/${mainModelId}/submodels/${submodelId}/presets`,
    payload,
  )
  return data
}

export async function patchRegistryPreset(
  workspaceId: string,
  mainModelId: string,
  submodelId: string,
  presetId: string,
  payload: PatchRegistryPresetPayload,
): Promise<TtsRegistryPresetRecord> {
  const { data } = await axios.patch<TtsRegistryPresetRecord>(
    `/v1/tts-registry/workspaces/${workspaceId}/main-models/${mainModelId}/submodels/${submodelId}/presets/${presetId}`,
    payload,
  )
  return data
}

export async function deleteRegistryPreset(
  workspaceId: string,
  mainModelId: string,
  submodelId: string,
  presetId: string,
): Promise<TtsRegistryDeleteResult> {
  const { data } = await axios.delete<TtsRegistryDeleteResult>(
    `/v1/tts-registry/workspaces/${workspaceId}/main-models/${mainModelId}/submodels/${submodelId}/presets/${presetId}`,
  )
  return data
}
