import axios from './http'
import type { 
  EditSessionSnapshot,
  InitializeRequest,
  RenderJobAcceptedResponse,
  RenderJobResponse,
  RenderJob,
  TimelineManifest,
  RenderJobEventType
} from '@/types/editSession'
import { unwrapAcceptedRenderJob } from './editSessionContract'
import { resolveApiUrl } from './requestSupport'

export async function getSnapshot(): Promise<EditSessionSnapshot> {
  const { data } = await axios.get<EditSessionSnapshot>('/v1/edit-session/snapshot')
  return data
}

export async function initializeSession(params: InitializeRequest): Promise<RenderJobResponse> {
  const { data } = await axios.post<RenderJobAcceptedResponse>('/v1/edit-session/initialize', params)
  return unwrapAcceptedRenderJob(data)
}

export async function getRenderJob(jobId: string): Promise<RenderJob> {
  const { data } = await axios.get<RenderJob>('/v1/edit-session/render-jobs/' + jobId)
  return data
}

export async function getTimeline(): Promise<TimelineManifest> {
  const { data } = await axios.get<TimelineManifest>('/v1/edit-session/timeline')
  return data
}

export interface RenderJobEventHandlers {
  onEvent?: (type: RenderJobEventType, payload: any) => void
  onError?: (err: Event) => void
  onComplete?: () => void
}

export function subscribeRenderJobEvents(jobId: string, handlers: RenderJobEventHandlers): () => void {
  const source = new EventSource(
    resolveApiUrl(
      `/v1/edit-session/render-jobs/${jobId}/events`,
      import.meta.env.VITE_API_BASE_URL || '',
    ),
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
    'job_completed',
    'job_failed',
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
