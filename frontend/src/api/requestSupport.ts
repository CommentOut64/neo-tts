export class ApiRequestError extends Error {
  readonly statusCode: number | null

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
    }
  }
  code?: string
}

export function toApiRequestError(error: ApiErrorLike): ApiRequestError {
  if (typeof error.response?.status === 'number') {
    const detail = error.response.data?.detail
    const message = typeof detail === 'string' && detail.trim().length > 0
      ? detail
      : `HTTP ${error.response.status}`
    return new ApiRequestError(message, error.response.status)
  }

  if (error.code === 'ECONNABORTED') {
    return new ApiRequestError('请求超时，请检查后端是否正常运行')
  }

  return new ApiRequestError('网络错误，请检查连接')
}

export function extractStatusCode(error: unknown): number | null {
  return error instanceof ApiRequestError ? error.statusCode : null
}

export function resolveApiUrl(path: string, baseUrl: string): string {
  const normalizedBase = String(baseUrl || '').trim().replace(/\/$/, '')
  return normalizedBase ? `${normalizedBase}${path}` : path
}
