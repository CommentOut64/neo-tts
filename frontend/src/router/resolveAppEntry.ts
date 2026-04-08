import { getSnapshot } from '@/api/editSession'
import { extractStatusCode } from '@/api/requestSupport'
import type { SessionStatus } from '@/composables/useEditSession'

export type AppEntryPath = '/text-input' | '/workspace'

function shouldEnterWorkspace(status: SessionStatus | null | undefined): boolean {
  return status != null && status !== 'empty'
}

export function resolveAppEntryFromStatus(status: SessionStatus | null | undefined): AppEntryPath {
  return shouldEnterWorkspace(status) ? '/workspace' : '/text-input'
}

export async function resolveAppEntryPath(
  loadSnapshot: typeof getSnapshot = getSnapshot,
): Promise<AppEntryPath> {
  try {
    const snapshot = await loadSnapshot()
    return resolveAppEntryFromStatus(snapshot.session_status)
  } catch (error) {
    if (extractStatusCode(error) === 404) {
      return '/text-input'
    }

    console.warn('[router] failed to resolve app entry, fallback to text input', error)
    return '/text-input'
  }
}
