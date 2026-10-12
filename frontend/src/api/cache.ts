/**
 * Pure updates of cached message lists from live events, so the UI moves the
 * moment an event arrives. A debounced refetch follows anyway and has the last word.
 */
import type { InfiniteData } from '@tanstack/react-query'

import { FILTER_STATES, type Filter, type MessagePage, type MessageSummary } from './types'

export type Pages = InfiniteData<MessagePage, string | undefined>

export function matches(filter: Filter, message: MessageSummary): boolean {
  const states = FILTER_STATES[filter]
  return states.length === 0 || states.includes(message.state)
}

/**
 * Puts the new version of a message into one cached list: replaced in place,
 * dropped when it left the tab, or added on top when it is new and belongs there.
 * Searches are left to the refetch: matching text is the server's job.
 */
export function applySummary(
  data: Pages,
  message: MessageSummary,
  filter: Filter,
  searching: boolean,
): Pages {
  const old = data.pages.flatMap((page) => page.items).find((item) => item.id === message.id)
  const keep = matches(filter, message)
  if (!old && (!keep || searching)) return data

  const pages = data.pages.map((page, index) => {
    let items = page.items
    if (old) {
      items = keep
        ? items.map((item) => (item.id === message.id ? message : item))
        : items.filter((item) => item.id !== message.id)
    } else if (index === 0) {
      items = [message, ...items]
    }
    return { ...page, items }
  })
  // Every page carries the counts; the first one is what the tabs read.
  const counts = { ...pages[0].counts }
  if (old?.state !== message.state) {
    if (old) counts[old.state] = Math.max(0, (counts[old.state] ?? 0) - 1)
    counts[message.state] = (counts[message.state] ?? 0) + 1
  }
  pages[0] = { ...pages[0], counts }
  return { ...data, pages }
}
