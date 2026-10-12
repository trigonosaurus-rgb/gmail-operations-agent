/**
 * Live updates over server-sent events.
 *
 * The stream opens first; its `ready` event then refreshes whatever was loaded,
 * so nothing that happened in between is lost. After a dropped connection the
 * browser reconnects by itself and sends Last-Event-ID, and the server replays
 * the gap (or sends `reset` when the gap is too long).
 */
import { type QueryClient, useQueryClient } from '@tanstack/react-query'
import { useEffect, useSyncExternalStore } from 'react'

import { applySummary, type Pages } from './cache'
import { keys } from './queries'
import type { Filter, LiveEvent } from './types'

// Every event type the pipeline writes (src/gmail_operations_agent/pipeline.py).
export const EVENT_TYPES = [
  'ingested',
  'triaged',
  'awaiting_approval',
  'approved',
  'rejected',
  'done',
  'dead',
  'action_started',
  'action_done',
  'action_failed',
  'action_recovered',
  'retry_scheduled',
  'retry_requested',
] as const

const REFETCH_DELAY_MS = 400

// --- connection state, for the header ----------------------------------------------

export type LiveState = 'connecting' | 'live' | 'offline'
let state: LiveState = 'connecting'
const listeners = new Set<() => void>()

function setState(next: LiveState) {
  if (next === state) return
  state = next
  for (const listener of listeners) listener()
}

export function useLiveState(): LiveState {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    () => state,
  )
}

// --- the stream --------------------------------------------------------------------

/** Keeps one event stream open; a new `session` (after a demo reset) reconnects. */
export function useLiveEvents(session: number): void {
  const client = useQueryClient()
  useEffect(() => {
    const source = new EventSource('/api/events')
    const refetch = debounce(() => {
      void client.invalidateQueries({ queryKey: keys.messages })
      void client.invalidateQueries({ queryKey: ['stats'] })
    }, REFETCH_DELAY_MS)

    source.addEventListener('ready', () => {
      setState('live')
      void client.invalidateQueries()
    })
    source.addEventListener('reset', () => void client.invalidateQueries())
    source.addEventListener('error', () => {
      // CLOSED means the browser gave up (for example the server answered 410);
      // otherwise it is already retrying.
      setState(source.readyState === EventSource.CLOSED ? 'offline' : 'connecting')
    })
    for (const type of EVENT_TYPES) {
      source.addEventListener(type, (message: MessageEvent<string>) => {
        applyLiveEvent(client, JSON.parse(message.data) as LiveEvent)
        refetch()
      })
    }
    return () => {
      refetch.cancel()
      source.close()
      setState('connecting')
    }
  }, [client, session])
}

export function applyLiveEvent(client: QueryClient, { message }: LiveEvent): void {
  if (!message) return
  for (const [key, data] of client.getQueriesData<Pages>({ queryKey: keys.messages })) {
    if (!data) continue
    const [, filter, q] = key as ReturnType<typeof keys.list>
    client.setQueryData<Pages>(key, applySummary(data, message, filter as Filter, q !== ''))
  }
  void client.invalidateQueries({ queryKey: keys.message(message.id) })
}

function debounce(fn: () => void, ms: number) {
  let timer: ReturnType<typeof setTimeout> | undefined
  const run = () => {
    clearTimeout(timer)
    timer = setTimeout(fn, ms)
  }
  run.cancel = () => clearTimeout(timer)
  return run
}
