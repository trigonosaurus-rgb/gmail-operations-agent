import { Link, useNavigate, useRouterState } from '@tanstack/react-router'
import { MailIcon, PlusIcon, SearchIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { useLiveState } from '@/api/live'
import { useStatus } from '@/api/queries'
import { Button } from '@/components/ui/button'
import { health, TONE_TEXT } from '@/lib/present'
import { cn } from '@/lib/utils'

import { QuickSettings } from './QuickSettings'
import { Dot } from './Status'

const NAV = [
  { to: '/', label: 'Inbox' },
  { to: '/stats', label: 'Stats' },
] as const

export function Header({ onCompose }: { onCompose: () => void }) {
  const status = useStatus()
  const live = useLiveState()
  const state = health(status.data, live)
  const demo = status.data?.source === 'demo'

  return (
    <header className="flex flex-wrap items-center gap-x-5 gap-y-1.5 border-b bg-page px-6 py-1.5 max-lg:px-4">
      <Link to="/" className="flex items-center gap-2.5 font-semibold text-fg no-underline">
        <span className="flex size-6 items-center justify-center rounded-xs bg-primary text-primary-fg">
          <MailIcon className="size-4" strokeWidth={2} />
        </span>
        <span className="max-lg:sr-only">Gmail Operations Agent</span>
      </Link>

      <nav aria-label="Main">
        <ul className="flex gap-0.5">
          {NAV.map((item) => (
            <li key={item.to}>
              <Link
                to={item.to}
                activeOptions={{ exact: true, includeSearch: false }}
                className="flex min-h-8 items-center rounded-sm px-3 text-muted-fg no-underline hover:text-fg data-[status=active]:bg-field data-[status=active]:font-medium data-[status=active]:text-fg"
              >
                {item.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      <Search />

      <div className="ml-auto flex items-center gap-4 max-sm:gap-3">
        <span
          role="status"
          title={state.detail || undefined}
          className={cn('flex items-center gap-2 text-[13px]', state.tone === 'ok' ? 'text-muted-fg' : TONE_TEXT[state.tone])}
        >
          <Dot tone={state.tone} className="size-[7px]" />
          <span className="max-md:sr-only">{state.label}</span>
        </span>
        {demo && (
          <>
            <Button variant="field" size="sm" onClick={onCompose}>
              <PlusIcon className="size-3.5" strokeWidth={2.2} />
              Test email
            </Button>
            <span
              title="Synthetic inbox: nothing reaches real Gmail, Notion or Sheets"
              className="caps tracking-[0.06em] text-muted-fg max-sm:hidden"
            >
              Demo
            </span>
          </>
        )}
        {status.data && <QuickSettings status={status.data} />}
      </div>
    </header>
  )
}

/** Searches the inbox; typing on another page takes you to the inbox. */
function Search() {
  const navigate = useNavigate()
  const { pathname, q } = useRouterState({
    select: (s) => ({ pathname: s.location.pathname, q: (s.location.search as { q?: string }).q ?? '' }),
  })
  const [text, setText] = useState(q)
  const typed = useRef(false)

  useEffect(() => {
    if (!typed.current) setText(q) // back/forward or a link changed the search
  }, [q])

  useEffect(() => {
    if (!typed.current) return
    const timer = setTimeout(() => {
      typed.current = false
      void navigate({
        to: '/',
        search: (prev) => ({ ...(pathname === '/' ? prev : {}), q: text.trim() || undefined }),
        replace: pathname === '/',
      })
    }, 250)
    return () => clearTimeout(timer)
  }, [text, navigate, pathname])

  return (
    <label className="flex min-h-8 max-w-90 flex-[1_1_220px] items-center gap-2 rounded-full bg-field px-4 text-muted-fg max-sm:order-last max-sm:max-w-none max-sm:basis-full">
      <SearchIcon className="size-4 shrink-0" />
      <span className="sr-only">Search emails</span>
      <input
        type="search"
        value={text}
        onChange={(e) => {
          typed.current = true
          setText(e.target.value)
        }}
        maxLength={200}
        placeholder="Search sender, subject, summary…"
        className="min-h-7.5 min-w-0 flex-1 bg-transparent text-[13px] text-fg outline-none placeholder:text-muted-fg"
      />
    </label>
  )
}
