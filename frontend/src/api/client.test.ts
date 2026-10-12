import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError, setSessionGoneHandler, url } from './client'

function reply(status: number, body: unknown) {
  return vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }),
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('url', () => {
  it('repeats list params and skips empty ones', () => {
    expect(url('/api/messages', { state: ['new', 'dead'], q: '', before: undefined, limit: 5 })).toBe(
      '/api/messages?state=new&state=dead&limit=5',
    )
  })
})

describe('api', () => {
  it('sends JSON and returns the parsed answer', async () => {
    const fetch = reply(200, { ok: true })
    vi.stubGlobal('fetch', fetch)
    await expect(api('/api/x', { method: 'POST', body: { a: 1 } })).resolves.toEqual({ ok: true })
    const [, init] = fetch.mock.calls[0]
    expect(init.body).toBe('{"a":1}')
    expect(init.headers).toEqual({ 'content-type': 'application/json' })
  })

  it("turns FastAPI's detail into the error message", async () => {
    vi.stubGlobal('fetch', reply(409, { detail: 'message is done, expected awaiting_approval' }))
    await expect(api('/api/x')).rejects.toEqual(new ApiError(409, 'message is done, expected awaiting_approval'))
  })

  it('names the first field of a validation error', async () => {
    vi.stubGlobal('fetch', reply(422, { detail: [{ loc: ['body', 'subject'], msg: 'Field required' }] }))
    await expect(api('/api/x')).rejects.toThrow('subject: Field required')
  })

  it('reports an expired demo session', async () => {
    const gone = vi.fn()
    setSessionGoneHandler(gone)
    vi.stubGlobal('fetch', reply(410, { detail: 'Your demo session expired.' }))
    await expect(api('/api/x', { method: 'POST' })).rejects.toBeInstanceOf(ApiError)
    expect(gone).toHaveBeenCalledOnce()
  })
})
