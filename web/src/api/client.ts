export interface ApiErrorDetail {
  code: string
  message: string
  field: string | null
}

export class ApiError extends Error {
  readonly status: number
  readonly detail: ApiErrorDetail | null
  constructor(status: number, detail: ApiErrorDetail | null, fallback: string) {
    super(detail?.message ?? fallback)
    this.status = status
    this.detail = detail
  }
}

export const API_BASE = '/api'

type Query = Record<string, string | number | boolean | null | undefined | Array<string | number>>

function buildUrl(path: string, query?: Query): string {
  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost'
  const url = new URL(`${API_BASE}${path}`, origin)
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v === null || v === undefined || v === '') continue
      if (Array.isArray(v)) v.forEach((x) => url.searchParams.append(k, String(x)))
      else url.searchParams.set(k, String(v))
    }
  }
  return url.toString()
}

async function handle<T>(res: Response): Promise<T> {
  if (res.ok) return (await res.json()) as T
  let detail: ApiErrorDetail | null = null
  try {
    const body = (await res.json()) as { detail?: unknown }
    if (body.detail && typeof body.detail === 'object' && 'message' in body.detail) {
      detail = body.detail as ApiErrorDetail
    } else if (typeof body.detail === 'string') {
      detail = { code: String(res.status), message: body.detail, field: null }
    }
  } catch {
    /* body was not JSON */
  }
  const fallback =
    res.status === 503 ? 'Data is not loaded yet on the server.' : `Request failed with status ${res.status}.`
  throw new ApiError(res.status, detail, fallback)
}

export async function apiGet<T>(path: string, query?: Query): Promise<T> {
  const res = await fetch(buildUrl(path, query), { headers: { Accept: 'application/json' } })
  return handle<T>(res)
}

export async function apiSend<T>(method: 'POST' | 'PUT', path: string, body?: unknown): Promise<T> {
  const res = await fetch(buildUrl(path), {
    method,
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  return handle<T>(res)
}
