import { getRouteApi } from '@tanstack/react-router'
import { useEffect } from 'react'

import { useMessages } from '@/api/queries'
import { useMediaQuery, WIDE } from '@/lib/hooks'

import { MessageList } from './MessageList'
import { MessagePane } from './MessagePane'

const route = getRouteApi('/')

/**
 * Wide screens show the list and the open email side by side, each scrolling on
 * its own. Phones show one at a time, and the `m` search param decides which.
 */
export function InboxPage() {
  const { m, filter = 'all', q = '' } = route.useSearch()
  const navigate = route.useNavigate()
  const wide = useMediaQuery(WIDE)
  const list = useMessages(filter, q)
  const first = list.data?.pages[0]?.items[0]?.id

  // Side by side, an empty pane is wasted space: open the newest email.
  useEffect(() => {
    if (wide && !m && first) void navigate({ search: (s) => ({ ...s, m: first }), replace: true })
  }, [wide, m, first, navigate])

  const back = () => void navigate({ search: (s) => ({ ...s, m: undefined }) })
  return (
    <main className="flex flex-1 gap-5 px-6 pt-4 pb-7 max-lg:flex-col max-lg:px-4 lg:min-h-0 lg:pb-6">
      <h1 className="sr-only">Inbox</h1>
      {(wide || !m) && <MessageList list={list} filter={filter} selected={m} searching={q !== ''} />}
      {(wide || m) && <MessagePane id={m} onBack={wide ? undefined : back} />}
    </main>
  )
}
