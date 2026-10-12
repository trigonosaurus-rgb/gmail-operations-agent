/** A small fetch wrapper: JSON in and out, FastAPI's `detail` turned into an error message. */

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

type Query = Record<string, string | number | string[] | null | undefined>

export function url(path: string, query: Query = {}): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value == null || value === '') continue
    for (const item of Array.isArray(value) ? value : [value]) params.append(key, String(item))
  }
  const qs = params.toString()
  return qs ? `${path}?${qs}` : path
}

let onSessionGone = () => window.location.reload()

/** The demo answers 410 when the visitor's sandbox expired; by default the page reloads. */
export function setSessionGoneHandler(handler: () => void): void {
  onSessionGone = handler
}

export async function api<T>(
  path: string,
  init: { method?: string; query?: Query; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  const response = await fetch(url(path, init.query), {
    method: init.method ?? 'GET',
    headers: init.body === undefined ? undefined : { 'content-type': 'application/json' },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
    credentials: 'same-origin',
    signal: init.signal,
  })
  if (!response.ok) {
    if (response.status === 410) onSessionGone()
    throw new ApiError(response.status, await errorMessage(response))
  }
  return (await response.json()) as T
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json()
    const detail = (body as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail.length > 0) {
      // A validation error: name the first field that failed.
      const first = detail[0] as { loc?: unknown[]; msg?: string }
      const field = first.loc?.at(-1)
      return [field, first.msg].filter(Boolean).join(': ')
    }
  } catch {
    // not JSON
  }
  return `${response.status} ${response.statusText}`.trim()
}
