import { ArrowLeftIcon, ArrowUpRightIcon } from 'lucide-react'
import { useState } from 'react'

import { ApiError } from '@/api/client'
import { useDecision, useMessage, useStatus } from '@/api/queries'
import type { ActionKind, MessageDetail } from '@/api/types'
import { Button } from '@/components/ui/button'
import { fullWhen, money, seconds } from '@/lib/format'
import {
  CATEGORY,
  isRisky,
  PRIORITY,
  PRIORITY_TONE,
  RISK,
  stateOf,
} from '@/lib/present'
import { cn } from '@/lib/utils'

import { Caps } from '../Status'
import { ActivityTab, OriginalTab } from './DetailTabs'
import { TriageTab } from './TriageTab'

/** What a reviewer changed before approving: actions left out and an edited reply. */
export interface Review {
  skip: Set<ActionKind>
  draft: string | undefined
}

export function MessagePane({ id, onBack }: { id?: string; onBack?: () => void }) {
  const message = useMessage(id)

  let body
  if (!id) body = <Placeholder>Select an email to see what the agent made of it.</Placeholder>
  else if (message.isPending) body = <Loading />
  else if (message.isError)
    body = (
      <Placeholder>
        {message.error instanceof ApiError && message.error.status === 404
          ? 'This email is no longer here.'
          : `Could not load this email: ${message.error.message}`}
      </Placeholder>
    )
  else body = <MessageView key={message.data.id} message={message.data} />

  return (
    <section
      aria-label="Selected email"
      className="relative flex w-full min-w-0 flex-1 flex-col rounded-lg bg-panel lg:overflow-y-auto"
    >
      {onBack && (
        <button
          type="button"
          onClick={onBack}
          className="flex min-h-11 items-center gap-2 self-start px-4 pt-2 text-muted-fg hover:text-fg"
        >
          <ArrowLeftIcon className="size-4" />
          Inbox
        </button>
      )}
      {body}
    </section>
  )
}

type Tab = 'triage' | 'original' | 'activity'
const TABS: [Tab, string][] = [
  ['triage', 'Triage'],
  ['original', 'Original email'],
  ['activity', 'Activity & cost'],
]

function MessageView({ message }: { message: MessageDetail }) {
  const [tab, setTab] = useState<Tab>('triage')
  const [review, setReview] = useState<Review>({ skip: new Set(), draft: undefined })
  const source = useStatus().data?.source ?? 'gmail'
  const state = stateOf(message)
  const triaged = message.state !== 'new' || !!message.triage
  const inReview = message.state === 'awaiting_approval'

  return (
    <>
      <header className="flex flex-col gap-3 px-6 pt-6 max-sm:px-4 max-lg:pt-3">
        <div className="flex flex-wrap items-start gap-3">
          <div className="flex min-w-0 flex-[1_1_320px] flex-col gap-1">
            <h2 className="text-[22px] leading-[1.3] font-semibold tracking-[-0.015em] text-pretty">
              {message.subject || '(no subject)'}
            </h2>
            <span className="text-muted-fg">
              {message.sender_name && <>{message.sender_name} · </>}
              <span className="font-mono text-[13px] break-all">{message.sender_address}</span> ·{' '}
              {fullWhen(message.received_at ?? message.created_at)}
            </span>
          </div>
          {message.email.web_url && (
            <Button asChild variant="well" size="sm" className="min-h-9 text-fg no-underline">
              <a href={message.email.web_url} target="_blank" rel="noreferrer">
                Open in Gmail
                <ArrowUpRightIcon className="size-3.5" />
              </a>
            </Button>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 [&>*]:text-xs [&>*]:tracking-[0.06em]">
          <Caps tone={state.tone} dot>
            {state.label}
          </Caps>
          {message.priority && triaged && (
            <Caps tone={PRIORITY_TONE[message.priority]}>{PRIORITY[message.priority]} priority</Caps>
          )}
          {message.category && <Caps>{CATEGORY[message.category]}</Caps>}
          {isRisky(message.risk) && <Caps tone="warn">Risk · {RISK[message.risk]}</Caps>}
        </div>
        <div role="tablist" aria-label="Email details" className="mt-2 flex gap-5 overflow-x-auto border-b">
          {TABS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={cn(
                'min-h-11 shrink-0 py-2.5 font-medium',
                tab === key ? 'text-fg shadow-[inset_0_-2px_0_var(--fg)]' : 'text-muted-fg hover:text-fg',
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </header>

      <div role="tabpanel" className="flex flex-1 flex-col gap-5 p-6 max-sm:px-4">
        {tab === 'triage' && <TriageTab message={message} review={review} onReview={setReview} />}
        {tab === 'original' && <OriginalTab message={message} />}
        {tab === 'activity' && <ActivityTab message={message} source={source} />}
      </div>

      {inReview ? (
        <ReviewBar message={message} review={review} />
      ) : (
        message.usage && (
          <footer className="border-t px-6 py-3 text-xs text-muted-fg max-sm:px-4">
            Triaged in {seconds(message.usage.latency_ms)} · {money(message.usage.cost_usd)}
            {message.usage.recorded && ' · replayed from a recorded run'}
          </footer>
        )
      )}
    </>
  )
}

function ReviewBar({ message, review }: { message: MessageDetail; review: Review }) {
  const decide = useDecision(message.id)
  const runs = message.actions.filter((a) => a.kind !== 'mark_processed' && !review.skip.has(a.kind)).length
  const original = message.triage?.reply?.body ?? ''
  const edited = review.draft !== undefined && review.draft.trim() !== original.trim()

  const approve = () =>
    decide.mutate({
      action: 'approve',
      body: { skip: [...review.skip], reply_body: edited ? review.draft : null },
    })
  return (
    <footer className="sticky bottom-0 z-[2] flex flex-wrap items-center gap-2.5 rounded-b-lg bg-panel px-6 py-3.5 shadow-[0_-1px_0_var(--hair)] max-sm:px-4">
      <span className={cn('flex-[1_1_240px] text-[13px] max-sm:basis-full', decide.error ? 'text-danger' : 'text-muted-fg')}>
        {decide.error ? decide.error.message : 'Reject keeps the email and only labels it as handled.'}
      </span>
      <Button variant="well" disabled={decide.isPending} onClick={() => decide.mutate({ action: 'reject' })}>
        Reject
      </Button>
      <Button variant="primary" disabled={decide.isPending} onClick={approve} className="max-sm:flex-1">
        {runs ? `Approve · run ${runs} ${runs === 1 ? 'action' : 'actions'}` : 'Approve · label only'}
      </Button>
    </footer>
  )
}

function Placeholder({ children }: { children: React.ReactNode }) {
  return <p className="m-auto max-w-80 p-10 text-center text-muted-fg">{children}</p>
}

function Loading() {
  return (
    <div aria-busy className="flex animate-pulse flex-col gap-3 p-6">
      <span className="h-6 w-2/3 rounded-xs bg-well" />
      <span className="h-3.5 w-1/3 rounded-xs bg-well" />
      <span className="mt-6 h-3.5 w-4/5 rounded-xs bg-well" />
      <span className="h-3.5 w-3/5 rounded-xs bg-well" />
    </div>
  )
}
