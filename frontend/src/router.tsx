import { createRootRoute, createRoute, createRouter } from '@tanstack/react-router'

import type { Filter } from '@/api/types'
import { AppShell } from '@/components/AppShell'
import { InboxPage } from '@/components/inbox/InboxPage'
import { StatsPage } from '@/components/stats/StatsPage'

// The URL holds what a person would want to share or come back to:
// the open email, the tab and the search.
export interface InboxSearch {
  m?: string
  filter?: Exclude<Filter, 'all'>
  q?: string
}

export const RANGES = [24, 168, 720] as const
export type Hours = (typeof RANGES)[number]

const rootRoute = createRootRoute({ component: AppShell })

const inboxRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  validateSearch: (search: Record<string, unknown>): InboxSearch => ({
    m: typeof search.m === 'string' && search.m ? search.m : undefined,
    filter: search.filter === 'review' || search.filter === 'dead' ? search.filter : undefined,
    q: typeof search.q === 'string' && search.q ? search.q.slice(0, 200) : undefined,
  }),
  component: InboxPage,
})

const statsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/stats',
  validateSearch: (search: Record<string, unknown>): { hours?: Hours } => {
    const hours = Number(search.hours)
    return { hours: RANGES.includes(hours as Hours) && hours !== 24 ? (hours as Hours) : undefined }
  },
  component: StatsPage,
})

export const router = createRouter({
  routeTree: rootRoute.addChildren([inboxRoute, statsRoute]),
  defaultPreload: false,
  scrollRestoration: true,
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
