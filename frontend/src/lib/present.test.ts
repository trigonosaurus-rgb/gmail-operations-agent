import { describe, expect, it } from 'vitest'

import type { ActionOut, EventOut, StatusOut } from '@/api/types'

import { actionMark, connectionLines, eventText, health, stateOf } from './present'

function action(overrides: Partial<ActionOut> = {}): ActionOut {
  return {
    kind: 'notion_task',
    status: 'pending',
    needs_approval: true,
    attempts: 0,
    preview: {},
    url: null,
    error: null,
    updated_at: '2026-10-12T10:00:00Z',
    ...overrides,
  }
}

function event(type: string, data: Record<string, unknown> = {}): EventOut {
  return { id: 1, message_id: 'm', type, data, created_at: '2026-10-12T10:00:00Z' }
}

function status(overrides: Partial<StatusOut['worker']> = {}): StatusOut {
  return {
    source: 'gmail',
    mode: 'review',
    model: 'gpt-6-luna',
    worker: { running: true, last_poll_at: null, last_error: null, blocked: null, in_flight: 0, ...overrides },
    connections: {
      gmail: { enabled: true, sandbox: false },
      notion: { enabled: true, sandbox: false },
      sheets: { enabled: false, sandbox: false },
    },
  }
}

describe('actionMark', () => {
  it('in review, splits what waits for a person from what simply runs', () => {
    expect(actionMark(action(), 'awaiting_approval')).toBe('review')
    expect(actionMark(action({ kind: 'sheets_row', needs_approval: false }), 'awaiting_approval')).toBe('queued')
    expect(actionMark(action(), 'awaiting_approval', true)).toBe('skipped')
  })

  it('after review, follows the stored status', () => {
    expect(actionMark(action({ status: 'done' }), 'done')).toBe('done')
    expect(actionMark(action({ status: 'failed' }), 'dead')).toBe('failed')
    expect(actionMark(action({ status: 'running' }), 'acting')).toBe('running')
  })

  it('calls pending work in a dead letter "not run yet", not "queued"', () => {
    expect(actionMark(action({ kind: 'mark_processed' }), 'dead')).toBe('notrun')
    expect(actionMark(action(), 'acting')).toBe('queued')
  })
})

describe('stateOf', () => {
  it('shows work waiting for another attempt as retrying', () => {
    expect(stateOf({ state: 'new', attempts: 0 }).label).toBe('Triaging')
    expect(stateOf({ state: 'new', attempts: 2 }).label).toBe('Retrying')
    expect(stateOf({ state: 'dead', attempts: 5 }).label).toBe('Dead letter')
  })
})

describe('eventText', () => {
  it('writes the activity log in plain words', () => {
    expect(eventText(event('triaged', { category: 'lead', priority: 'high', risk: 'phishing' }))).toBe(
      'Triaged · lead, high · risk phishing',
    )
    expect(eventText(event('approved', { by: 'you' }))).toBe('Approved by you')
    expect(eventText(event('approved', { by: 'demo scenario' }))).toBe('Approved by the demo scenario')
    expect(eventText(event('action_done', { kind: 'gmail_draft' }))).toBe('Gmail draft saved')
    expect(eventText(event('ingested'), 'demo')).toBe('Arrived in the demo inbox')
  })

  it('hides noise and does not repeat an action error', () => {
    expect(eventText(event('action_started', { kind: 'notion_task' }))).toBeNull()
    expect(eventText(event('dead', { error: 'notion_task: 400' }))).toBe('Moved to dead letters')
    expect(eventText(event('dead', { error: 'parse error: bad MIME' }))).toBe(
      'Moved to dead letters: parse error: bad MIME',
    )
  })
})

describe('health', () => {
  it('puts the most serious problem first', () => {
    expect(health(status(), 'offline').label).toBe('Offline')
    expect(health(status(), 'connecting').label).toBe('Connecting…')
    expect(health(status({ running: false }), 'live').tone).toBe('danger')
    expect(health(status({ blocked: { service: 'notion', reason: 'invalid token', until: null } }), 'live')).toMatchObject({
      label: 'Notion paused',
      tone: 'warn',
    })
    expect(health(status({ blocked: { service: 'openai', reason: 'quota exhausted', until: null } }), 'live').label).toBe(
      'OpenAI paused',
    )
    expect(health(status(), 'live')).toMatchObject({ label: 'All connected', tone: 'ok' })
  })

  it('lists connections with what each one does', () => {
    expect(connectionLines(status()).map((line) => line.text)).toEqual(['polling', 'connected', 'off'])
  })
})
