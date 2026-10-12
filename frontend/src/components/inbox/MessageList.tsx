import { getRouteApi } from '@tanstack/react-router'

import { type useMessages, useStats } from '@/api/queries'
import type { Filter, MessagePage } from '@/api/types'
import { Button } from '@/components/ui/button'
import { money, seconds } from '@/lib/format'
import { cn } from '@/lib/utils'

import { MessageRow } from './MessageRow'

const route = getRouteApi('/')

type Counts = MessagePage['counts']

const TABS: { key: Filter; label: string; count: (c: Counts) => number }[] = [
  { key: 'all', label: 'All', count: (c) => Object.values(c).reduce((a, b) => a + (b ?? 0), 0) },
  { key: 'review', label: 'Needs review', count: (c) => c.awaiting_approval ?? 0 },
  { key: 'dead', label: 'Dead letters', count: (c) => c.dead ?? 0 },
]

export function MessageList({
  list,
  filter,
  selected,
  searching,
}: {
  list: ReturnType<typeof useMessages>
  filter: Filter
  selected?: string
  searching: boolean
}) {
  const items = list.data?.pages.flatMap((page) => page.items) ?? []

  return (
    <section
      aria-label="Messages"
      className="-mx-3 flex min-w-0 flex-col lg:mr-0 lg:w-105 lg:shrink-0 lg:overflow-y-auto"
    >
      <Tabs filter={filter} counts={list.data?.pages[0]?.counts} />
      {list.isPending ? (
        <Skeleton />
      ) : list.isError ? (
        <p className="border-t px-3 py-6 text-danger">Could not load the inbox: {list.error.message}</p>
      ) : items.length === 0 ? (
        <p className="border-t px-3 py-6 text-muted-fg">
          {searching ? 'Nothing matches this search.' : 'No emails in this view.'}
        </p>
      ) : (
        <ul className={cn('transition-opacity', list.isPlaceholderData && 'opacity-60')}>
          {items.map((message) => (
            <MessageRow key={message.id} message={message} selected={message.id === selected} />
          ))}
        </ul>
      )}
      {list.hasNextPage && (
        <Button
          variant="field"
          className="mx-3 my-3"
          onClick={() => void list.fetchNextPage()}
          disabled={list.isFetchingNextPage}
        >
          {list.isFetchingNextPage ? 'Loading…' : 'Show older'}
        </Button>
      )}
      <Spend />
    </section>
  )
}

function Tabs({ filter, counts }: { filter: Filter; counts?: Counts }) {
  const navigate = route.useNavigate()
  return (
    <div role="tablist" aria-label="Filter" className="sticky top-0 z-[1] flex flex-wrap gap-0.5 bg-page pb-2">
      {TABS.map((tab) => {
        const active = tab.key === filter
        return (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() =>
              void navigate({
                search: (s) => ({ ...s, filter: tab.key === 'all' ? undefined : tab.key, m: undefined }),
              })
            }
            className={cn(
              'flex min-h-9 items-center gap-1.5 rounded-sm px-3 text-[13px] font-medium',
              active ? 'bg-field text-fg' : 'text-muted-fg hover:text-fg',
            )}
          >
            {tab.label}
            {counts && <span className="text-xs font-normal text-muted-fg">{tab.count(counts)}</span>}
          </button>
        )
      })}
    </div>
  )
}

/** Cost and speed stay out of the header: one quiet line under the list. */
function Spend() {
  const stats = useStats(24)
  const llm = stats.data?.llm
  if (!llm || llm.calls === 0) return null
  return (
    <p className="mt-auto border-t px-3 pt-3.5 text-xs text-muted-fg">
      Last 24 h {money(llm.cost_usd)} · median triage {seconds(llm.latency_ms.p50)}
    </p>
  )
}

function Skeleton() {
  return (
    <ul aria-busy className="animate-pulse">
      {[0, 1, 2, 3].map((i) => (
        <li key={i} className="flex flex-col gap-2.5 border-t px-3 py-4">
          <span className="h-3 w-1/3 rounded-xs bg-field" />
          <span className="h-3 w-3/4 rounded-xs bg-field" />
          <span className="h-3 w-2/3 rounded-xs bg-field" />
        </li>
      ))}
    </ul>
  )
}
