export class ApiRequestError extends Error {
  readonly statusCode: number | null
  readonly projectError?: {
    code?: unknown
    phase?: unknown
    retryable?: unknown
    action?: unknown
    request_id?: unknown
    message?: unknown
  }

  constructor(message: string, statusCode: number | null = null) {
    super(message)
    this.name = 'ApiRequestError'
    this.statusCode = statusCode
  }
}

interface ApiErrorLike {
  response?: {
    status?: number
    data?: {
      detail?: unknown
      error?: unknown
    }
  }
  code?: string
}

export function toApiRequestError(error: ApiErrorLike): ApiRequestError {
  if (typeof error.response?.status === 'number') {
    const detail = error.response.data?.detail
    const envelope = error.response.data?.error
    const message = extractErrorMessage(envelope) ?? extractErrorMessage(detail) ?? `HTTP ${error.response.status}`
    const apiError = new ApiRequestError(message, error.response.status)
    if (envelope && typeof envelope === "object") {
      Object.assign(apiError, { projectError: envelope })
    }
    return apiError
  }

  if (error.code === 'ECONNABORTED') {
    return new ApiRequestError('请求超时，请检查后端是否正常运行')
  }

  return new ApiRequestError('网络错误，请检查连接')
}

function extractErrorMessage(value: unknown): string | null {
  if (typeof value === "string" && value.trim().length > 0) {
    return value
  }
  if (value && typeof value === "object") {
    const message = (value as { message?: unknown }).message
    if (typeof message === "string" && message.trim().length > 0) {
      return message
    }
  }
  return null
}

export function extractStatusCode(error: unknown): number | null {
  return error instanceof ApiRequestError ? error.statusCode : null
}

export function resolveApiUrl(path: string, baseUrl: string): string {
  const normalizedBase = String(baseUrl || '').trim().replace(/\/$/, '')
  return normalizedBase ? `${normalizedBase}${path}` : path
}
