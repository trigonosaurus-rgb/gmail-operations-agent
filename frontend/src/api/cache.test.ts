import { describe, expect, it } from 'vitest'

import { applySummary, type Pages } from './cache'
import type { MessageState, MessageSummary } from './types'

function message(id: string, state: MessageState = 'new'): MessageSummary {
  return {
    id,
    state,
    sender_name: 'Anna',
    sender_address: 'anna@example.com',
    subject: id,
    received_at: null,
    summary: null,
    category: null,
    priority: null,
    risk: null,
    has_task: false,
    has_reply: false,
    attempts: 0,
    next_attempt_at: null,
    error: null,
    created_at: '2026-10-12T10:00:00Z',
    updated_at: '2026-10-12T10:00:00Z',
  }
}

function pages(...items: MessageSummary[][]): Pages {
  const counts: Record<string, number> = {}
  for (const item of items.flat()) counts[item.state] = (counts[item.state] ?? 0) + 1
  return {
    pageParams: items.map(() => undefined),
    pages: items.map((page) => ({ items: page, next_before: null, cursor: 1, counts })),
  }
}

const ids = (data: Pages) => data.pages.map((page) => page.items.map((item) => item.id))

describe('applySummary', () => {
  it('replaces a message in place, on whichever page it is', () => {
    const data = pages([message('a')], [message('b')])
    const next = applySummary(data, message('b', 'awaiting_approval'), 'all', false)
    expect(ids(next)).toEqual([['a'], ['b']])
    expect(next.pages[1].items[0].state).toBe('awaiting_approval')
    expect(next.pages[0].counts).toMatchObject({ new: 1, awaiting_approval: 1 })
  })

  it('drops a message that left the tab and fixes the counts', () => {
    const data = pages([message('a', 'awaiting_approval'), message('b', 'awaiting_approval')])
    const next = applySummary(data, message('a', 'acting'), 'review', false)
    expect(ids(next)).toEqual([['b']])
    expect(next.pages[0].counts).toMatchObject({ awaiting_approval: 1, acting: 1 })
  })

  it('adds a new message on top when it belongs to the tab', () => {
    const data = pages([message('a')])
    const next = applySummary(data, message('new-one'), 'all', false)
    expect(ids(next)).toEqual([['new-one', 'a']])
    expect(next.pages[0].counts.new).toBe(2)
  })

  it('leaves unknown messages to the refetch while searching or outside the tab', () => {
    const data = pages([message('a', 'dead')])
    expect(applySummary(data, message('x'), 'all', true)).toBe(data)
    expect(applySummary(data, message('x'), 'dead', false)).toBe(data)
  })

  it('does not touch the input', () => {
    const data = pages([message('a')])
    const before = structuredClone(data)
    applySummary(data, message('a', 'done'), 'all', false)
    expect(data).toEqual(before)
  })
})
