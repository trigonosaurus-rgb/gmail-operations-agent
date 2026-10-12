import { Outlet } from '@tanstack/react-router'
import { useMemo, useState } from 'react'

import { useLiveEvents } from '@/api/live'
import { SessionContext } from '@/lib/session'

import { Composer } from './Composer'
import { Header } from './Header'

export function AppShell() {
  const [session, setSession] = useState(0)
  const [composing, setComposing] = useState(false)
  useLiveEvents(session)
  const context = useMemo(() => ({ session, restart: () => setSession((n) => n + 1) }), [session])

  return (
    <SessionContext value={context}>
      {/* Wide screens: a fixed-height app with panes that scroll on their own. */}
      <div className="flex min-h-dvh flex-col lg:h-dvh lg:overflow-hidden">
        <Header onCompose={() => setComposing(true)} />
        <Outlet />
      </div>
      <Composer open={composing} onOpenChange={setComposing} />
    </SessionContext>
  )
}
