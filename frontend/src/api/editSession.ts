import axios from './http'
import type {
  EditSessionSnapshot,
  SegmentListResponse,
  EdgeListResponse,
  GroupListResponse,
  InitializeRequest,
  ConfigurationCommitResponse,
  ReferenceAudioUploadResponse,
  RenderProfileListResponse,
  RenderProfilePatch,
  RenderJobAcceptedResponse,
  RenderJobResponse,
  RenderJob,
  RenderJobStatus,
  TimelineManifest,
  RenderJobEventType,
  VoiceBindingListResponse,
  VoiceBindingPatch,
  SegmentBatchRenderProfilePatchBody,
  SegmentBatchVoiceBindingPatchBody,
  EdgeUpdateBody,
  ReorderSegmentsBody,
  ExportRequestBody,
  ExportJobResponse,
  ExportJobAcceptedResponse,
} from "@/types/editSession";
import {
  unwrapAcceptedRenderJob,
  unwrapAcceptedExportJob,
} from "./editSessionContract";
import { resolveBackendUrl } from '@/platform/runtimeConfig'

export async function getSnapshot(): Promise<EditSessionSnapshot> {
  const { data } = await axios.get<EditSessionSnapshot>('/v1/edit-session/snapshot')
  return data
}

export async function initializeSession(params: InitializeRequest): Promise<RenderJobResponse> {
  const { data } = await axios.post<RenderJobAcceptedResponse>('/v1/edit-session/initialize', params)
  return unwrapAcceptedRenderJob(data)
}

export async function uploadEditSessionReferenceAudio(file: File): Promise<ReferenceAudioUploadResponse> {
  const form = new FormData()
  form.append('ref_audio_file', file)
  const { data } = await axios.post<ReferenceAudioUploadResponse>('/v1/edit-session/reference-audio', form)
  return data
}

export async function getRenderJob(jobId: string): Promise<RenderJob> {
  const { data } = await axios.get<RenderJob>('/v1/edit-session/render-jobs/' + jobId)
  return data
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    globalThis.setTimeout(resolve, ms)
  })
}

export async function waitForRenderJobTerminal(
  jobId: string,
  options: {
    timeoutMs?: number
    pollIntervalMs?: number
    terminalStatuses?: RenderJobStatus[]
  } = {},
): Promise<RenderJobStatus> {
  const timeoutMs = options.timeoutMs ?? 10000
  const pollIntervalMs = options.pollIntervalMs ?? 200
  const terminalStatuses = new Set<RenderJobStatus>(
    options.terminalStatuses ?? ['paused', 'completed', 'failed', 'cancelled_partial'],
  )
  const deadline = Date.now() + timeoutMs

  while (true) {
    const job = await getRenderJob(jobId)
    if (terminalStatuses.has(job.status)) {
      return job.status
    }
    if (Date.now() >= deadline) {
      throw new Error(`等待 render job 进入终态超时: ${jobId}`)
    }
    await sleep(pollIntervalMs)
  }
}

export async function getTimeline(): Promise<TimelineManifest> {
  const { data } = await axios.get<TimelineManifest>('/v1/edit-session/timeline')
  return data
}

export async function listSegments(limit = 1000, cursor: number | null = null): Promise<SegmentListResponse> {
  const { data } = await axios.get<SegmentListResponse>('/v1/edit-session/segments', {
    params: {
      limit,
      ...(cursor === null ? {} : { cursor }),
    },
  })
  return data
}

export async function listEdges(limit = 1000, cursor: number | null = null): Promise<EdgeListResponse> {
  const { data } = await axios.get<EdgeListResponse>('/v1/edit-session/edges', {
    params: {
      limit,
      ...(cursor === null ? {} : { cursor }),
    },
  })
  return data
}

export async function getGroups(): Promise<GroupListResponse> {
  const { data } = await axios.get<GroupListResponse>('/v1/edit-session/groups')
  return data
}

export async function getRenderProfiles(): Promise<RenderProfileListResponse> {
  const { data } = await axios.get<RenderProfileListResponse>('/v1/edit-session/render-profiles')
  return data
}

export async function getVoiceBindings(): Promise<VoiceBindingListResponse> {
  const { data } = await axios.get<VoiceBindingListResponse>('/v1/edit-session/voice-bindings')
  return data
}

export async function deleteSession(): Promise<void> {
  await axios.delete('/v1/edit-session')
}

export async function updateSegment(
  id: string,
  updateData: {
    raw_text?: string
    text_language?: string
    inference_override?: Record<string, unknown>
  },
): Promise<RenderJobResponse> {
  const { data } = await axios.patch<RenderJobAcceptedResponse>(
    `/v1/edit-session/segments/${id}`,
    updateData,
  );
  return unwrapAcceptedRenderJob(data);
}

export async function rerenderSegment(id: string): Promise<RenderJobResponse> {
  const { data } = await axios.post<RenderJobAcceptedResponse>(
    `/v1/edit-session/segments/${id}/rerender`,
  );
  return unwrapAcceptedRenderJob(data);
}

export async function deleteSegment(segmentId: string): Promise<RenderJobResponse> {
  const { data } = await axios.delete<RenderJobAcceptedResponse>(
    `/v1/edit-session/segments/${segmentId}`,
  );
  return unwrapAcceptedRenderJob(data);
}

export async function updateEdge(edgeId: string, body: EdgeUpdateBody): Promise<RenderJobResponse> {
  const { data } = await axios.patch<RenderJobAcceptedResponse>(
    `/v1/edit-session/edges/${edgeId}`,
    body,
  )
  return unwrapAcceptedRenderJob(data)
}

export async function reorderSegments(
  body: ReorderSegmentsBody,
): Promise<RenderJobResponse> {
  const { data } = await axios.post<RenderJobAcceptedResponse>(
    "/v1/edit-session/segments/reorder",
    body,
  )
  return unwrapAcceptedRenderJob(data)
}

export async function patchSessionRenderProfile(body: RenderProfilePatch): Promise<RenderJobResponse> {
  const { data } = await axios.patch<RenderJobAcceptedResponse>(
    '/v1/edit-session/session/render-profile',
    body,
  )
  return unwrapAcceptedRenderJob(data)
}

export async function commitSessionRenderProfile(body: RenderProfilePatch): Promise<ConfigurationCommitResponse> {
  const { data } = await axios.patch<ConfigurationCommitResponse>(
    '/v1/edit-session/session/render-profile/config',
    body,
  )
  return data
}

export async function patchSessionVoiceBinding(body: VoiceBindingPatch): Promise<RenderJobResponse> {
  const { data } = await axios.patch<RenderJobAcceptedResponse>(
    '/v1/edit-session/session/voice-binding',
    body,
  )
  return unwrapAcceptedRenderJob(data)
}

export async function commitSessionVoiceBinding(body: VoiceBindingPatch): Promise<ConfigurationCommitResponse> {
  const { data } = await axios.patch<ConfigurationCommitResponse>(
    '/v1/edit-session/session/voice-binding/config',
    body,
  )
  return data
}

export async function patchSegmentRenderProfile(
  segmentId: string,
  body: RenderProfilePatch,
): Promise<RenderJobResponse> {
  const { data } = await axios.patch<RenderJobAcceptedResponse>(
    `/v1/edit-session/segments/${segmentId}/render-profile`,
    body,
  )
  return unwrapAcceptedRenderJob(data)
}

export async function commitSegmentRenderProfile(
  segmentId: string,
  body: RenderProfilePatch,
): Promise<ConfigurationCommitResponse> {
  const { data } = await axios.patch<ConfigurationCommitResponse>(
    `/v1/edit-session/segments/${segmentId}/render-profile/config`,
    body,
  )
  return data
}

export async function patchSegmentVoiceBinding(
  segmentId: string,
  body: VoiceBindingPatch,
): Promise<RenderJobResponse> {
  const { data } = await axios.patch<RenderJobAcceptedResponse>(
    `/v1/edit-session/segments/${segmentId}/voice-binding`,
    body,
  )
  return unwrapAcceptedRenderJob(data)
}

export async function commitSegmentVoiceBinding(
  segmentId: string,
  body: VoiceBindingPatch,
): Promise<ConfigurationCommitResponse> {
  const { data } = await axios.patch<ConfigurationCommitResponse>(
    `/v1/edit-session/segments/${segmentId}/voice-binding/config`,
    body,
  )
  return data
}

export async function patchSegmentRenderProfileBatch(
  body: SegmentBatchRenderProfilePatchBody,
): Promise<RenderJobResponse> {
  const { data } = await axios.patch<RenderJobAcceptedResponse>(
    '/v1/edit-session/segments/render-profile-batch',
    body,
  )
  return unwrapAcceptedRenderJob(data)
}

export async function commitSegmentRenderProfileBatch(
  body: SegmentBatchRenderProfilePatchBody,
): Promise<ConfigurationCommitResponse> {
  const { data } = await axios.patch<ConfigurationCommitResponse>(
    '/v1/edit-session/segments/render-profile-batch/config',
    body,
  )
  return data
}

export async function patchSegmentVoiceBindingBatch(
  body: SegmentBatchVoiceBindingPatchBody,
): Promise<RenderJobResponse> {
  const { data } = await axios.patch<RenderJobAcceptedResponse>(
    '/v1/edit-session/segments/voice-binding-batch',
    body,
  )
  return unwrapAcceptedRenderJob(data)
}

export async function commitSegmentVoiceBindingBatch(
  body: SegmentBatchVoiceBindingPatchBody,
): Promise<ConfigurationCommitResponse> {
  const { data } = await axios.patch<ConfigurationCommitResponse>(
    '/v1/edit-session/segments/voice-binding-batch/config',
    body,
  )
  return data
}

export async function commitEdgeConfig(
  edgeId: string,
  body: EdgeUpdateBody,
): Promise<ConfigurationCommitResponse> {
  const { data } = await axios.patch<ConfigurationCommitResponse>(
    `/v1/edit-session/edges/${edgeId}/config`,
    body,
  )
  return data
}

export interface RenderJobEventHandlers {
  onEvent?: (type: RenderJobEventType, payload: any) => void
  onError?: (err: Event) => void
  onOpen?: () => void
  onComplete?: () => void
}

export function subscribeRenderJobEvents(jobId: string, handlers: RenderJobEventHandlers): () => void {
  const source = new EventSource(
    resolveBackendUrl(`/v1/edit-session/render-jobs/${jobId}/events`),
  )

  const eventTypes: RenderJobEventType[] = [
    'job_state_changed',
    'segments_initialized',
    'segment_completed',
    'block_completed',
    'timeline_committed',
    'job_paused',
    'job_resumed',
    'job_cancelled_partial',
  ]

  const listeners = eventTypes.map((eventType) => {
    const listener = (event: MessageEvent<string>) => {
      try {
        const payload = JSON.parse(event.data)
        handlers.onEvent?.(eventType, payload)
      } catch (err) {
        console.error('Failed to parse SSE message', err)
      }
    }

    source.addEventListener(eventType, listener as unknown as EventListener)
    return { eventType, listener }
  })

  source.onopen = () => {
    handlers.onOpen?.()
  }
  source.onerror = (e) => {
    if (handlers.onError) handlers.onError(e)
    source.close()
  }

  return () => {
    for (const { eventType, listener } of listeners) {
      source.removeEventListener(eventType, listener as unknown as EventListener)
    }
    source.close()
  }
}

export async function pauseRenderJob(jobId: string): Promise<void> {
  await axios.post('/v1/edit-session/render-jobs/' + jobId + '/pause')
}
export async function cancelRenderJob(jobId: string): Promise<void> {
  await axios.post('/v1/edit-session/render-jobs/' + jobId + '/cancel')
}
export async function resumeRenderJob(jobId: string): Promise<RenderJobResponse> {
  const { data } = await axios.post<RenderJobAcceptedResponse>(
    '/v1/edit-session/render-jobs/' + jobId + '/resume',
  )
  return unwrapAcceptedRenderJob(data)
}

export async function exportAudio(
  body: ExportRequestBody,
): Promise<ExportJobResponse> {
  const { data } = await axios.post<ExportJobAcceptedResponse>(
    "/v1/edit-session/exports",
    body,
  );
  return unwrapAcceptedExportJob(data);
}

export async function exportSegments(
  body: Omit<ExportRequestBody, "audio"> & {
    overwrite_policy?: "fail" | "replace" | "new_folder";
  },
): Promise<ExportJobResponse> {
  return exportAudio({
    document_version: body.document_version,
    target_dir: body.target_dir,
    audio: {
      kind: "segments",
      overwrite_policy: body.overwrite_policy ?? "fail",
    },
    subtitle: body.subtitle,
  });
}

export async function exportComposition(
  body: Omit<ExportRequestBody, "audio"> & {
    overwrite_policy?: "fail" | "replace" | "new_folder";
  },
): Promise<ExportJobResponse> {
  return exportAudio({
    document_version: body.document_version,
    target_dir: body.target_dir,
    audio: {
      kind: "composition",
      overwrite_policy: body.overwrite_policy ?? "fail",
    },
    subtitle: body.subtitle,
  });
}

export async function getExportJob(jobId: string): Promise<ExportJobResponse> {
  const { data } = await axios.get<ExportJobResponse>(
    "/v1/edit-session/exports/" + jobId,
  );
  return data;
}

export type ExportJobEventType =
  | "job_state_changed"
  | "export_progress"
  | "export_completed";

export interface ExportJobEventHandlers {
  onStateChanged?: (job: ExportJobResponse) => void;
  onProgress?: (progress: number, message: string) => void;
  onCompleted?: (job: ExportJobResponse) => void;
  onError?: (err: unknown) => void;
  onComplete?: () => void;
}

export function subscribeExportJobEvents(
  jobId: string,
  handlers: ExportJobEventHandlers,
): () => void {
  const source = new EventSource(
    resolveBackendUrl("/v1/edit-session/exports/" + jobId + "/events"),
  );

  const eventTypes: ExportJobEventType[] = [
    "job_state_changed",
    "export_progress",
    "export_completed",
  ];

  for (const type of eventTypes) {
    source.addEventListener(type, (e: MessageEvent) => {
      try {
        const payload = JSON.parse(e.data);
        if (type === "job_state_changed" && handlers.onStateChanged) {
          handlers.onStateChanged(payload as ExportJobResponse);
        } else if (type === "export_progress" && handlers.onProgress) {
          handlers.onProgress(payload.progress, payload.message);
        } else if (type === "export_completed" && handlers.onCompleted) {
          handlers.onCompleted(payload as ExportJobResponse);
        }
      } catch (err) {
        handlers.onError?.(err);
      }
    });
  }

  source.onerror = (err) => {
    handlers.onError?.(err);
  };

  return () => {
    source.close();
    handlers.onComplete?.();
  };
}
