import {
  ArrowUpRightIcon,
  CornerUpLeftIcon,
  SquareCheckIcon,
  TableIcon,
  TagIcon,
  TriangleAlertIcon,
} from 'lucide-react'

import { useDecision } from '@/api/queries'
import type { ActionKind, ActionOut, MessageDetail } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { clock, fullWhen } from '@/lib/format'
import {
  ACTION_TITLE,
  actionMark,
  actionNote,
  canSkip,
  isRisky,
  MARK,
  RISK_TITLE,
} from '@/lib/present'

import { Caps } from '../Status'
import type { Review } from './MessagePane'

const ICON: Record<ActionKind, typeof TagIcon> = {
  notion_task: SquareCheckIcon,
  sheets_row: TableIcon,
  gmail_draft: CornerUpLeftIcon,
  mark_processed: TagIcon,
}

export function TriageTab({
  message,
  review,
  onReview,
}: {
  message: MessageDetail
  review: Review
  onReview: (review: Review) => void
}) {
  const triage = message.triage
  return (
    <>
      {message.state === 'new' && <Triaging message={message} />}
      {message.state === 'acting' && message.attempts > 0 && message.error && (
        <RetryNote message={message} />
      )}
      {triage && isRisky(triage.risk) && (
        <div role="note" className="flex max-w-180 gap-3 rounded-sm bg-warn-soft px-4 py-3">
          <TriangleAlertIcon className="mt-0.5 size-[18px] shrink-0 text-warn" />
          <div className="flex flex-col gap-1">
            <span className="font-semibold text-warn">{RISK_TITLE[triage.risk]}</span>
            {triage.risk_reason && <span>{triage.risk_reason}</span>}
            <span className="text-[13px] opacity-75">
              Code guardrail: a risky email never gets a task or a reply draft. Only the log row and
              the label are written.
            </span>
          </div>
        </div>
      )}
      {message.state === 'dead' && <DeadLetter message={message} />}
      {triage && (
        <div className="flex flex-col gap-1.5">
          <span className="text-[13px] font-medium text-muted-fg">Summary</span>
          <p className="max-w-[75ch] text-[15px] leading-relaxed">{triage.summary}</p>
          {message.notes.map((note) => (
            <p key={note} className="text-[13px] text-muted-fg">
              Guardrail: {note}
            </p>
          ))}
        </div>
      )}
      {message.actions.length > 0 && (
        <div className="flex flex-col">
          <span className="pb-2 text-[13px] font-medium text-muted-fg">{actionsTitle(message)}</span>
          {message.actions.map((action) => (
            <ActionItem
              key={action.kind}
              action={action}
              message={message}
              review={review}
              onReview={onReview}
            />
          ))}
        </div>
      )}
    </>
  )
}

function actionsTitle(message: MessageDetail): string {
  switch (message.state) {
    case 'awaiting_approval':
      return 'Planned actions'
    case 'acting':
      return 'Actions · running'
    case 'done':
    case 'rejected':
      return `Actions · finished ${fullWhen(message.updated_at)}`
    default:
      return 'Actions'
  }
}

function ActionItem({
  action,
  message,
  review,
  onReview,
}: {
  action: ActionOut
  message: MessageDetail
  review: Review
  onReview: (review: Review) => void
}) {
  const inReview = message.state === 'awaiting_approval'
  const skipped = review.skip.has(action.kind)
  const mark = MARK[actionMark(action, message.state, skipped)]
  const note = actionNote(action.kind, actionMark(action, message.state, skipped))
  const Icon = ICON[action.kind]
  const preview = action.preview as Record<string, unknown>
  const show = !skipped && action.status !== 'skipped'

  const toggle = (include: boolean) => {
    const skip = new Set(review.skip)
    if (include) skip.delete(action.kind)
    else skip.add(action.kind)
    onReview({ ...review, skip })
  }

  return (
    <div className="flex flex-col gap-2 border-t py-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="flex size-7 items-center justify-center rounded-xs bg-well">
          <Icon className="size-[15px]" />
        </span>
        <span className="font-semibold">{ACTION_TITLE[action.kind]}</span>
        <Caps tone={mark.tone}>{mark.label}</Caps>
        {inReview && canSkip(action.kind) && (
          <label className="ml-auto flex min-h-8 items-center gap-2 text-[13px] text-muted-fg">
            <Checkbox checked={!skipped} onCheckedChange={(on) => toggle(on === true)} />
            Include
          </label>
        )}
        {action.url && (
          <a
            href={action.url}
            target="_blank"
            rel="noreferrer"
            className="ml-auto flex items-center gap-1 text-[13px] text-muted-fg hover:text-fg"
          >
            Open <ArrowUpRightIcon className="size-3.5" />
          </a>
        )}
      </div>
      {note && <span className="text-[13px] text-muted-fg">{note}</span>}
      {action.error && message.state !== 'dead' && (
        <code className="font-mono text-xs break-words text-danger">{action.error}</code>
      )}
      {show && action.kind === 'notion_task' && (
        <div className="flex flex-col gap-1 rounded-sm bg-well px-3.5 py-3">
          <span className="font-semibold">{String(preview.title ?? '')}</span>
          {!!preview.description && (
            <span className="text-muted-fg">{String(preview.description)}</span>
          )}
          <span className="text-xs font-medium">
            {preview.due_date ? `Due ${String(preview.due_date)}` : 'No deadline in the email'}
          </span>
        </div>
      )}
      {show && action.kind === 'sheets_row' && Array.isArray(preview.row) && (
        <div className="overflow-x-auto rounded-sm bg-well px-3 py-2 font-mono text-xs whitespace-nowrap text-muted-fg">
          {(preview.row as unknown[]).filter((cell) => cell !== '').map(String).join('  │  ')}
        </div>
      )}
      {show && action.kind === 'gmail_draft' && (
        <Draft action={action} inReview={inReview} review={review} onReview={onReview} />
      )}
    </div>
  )
}

function Draft({
  action,
  inReview,
  review,
  onReview,
}: {
  action: ActionOut
  inReview: boolean
  review: Review
  onReview: (review: Review) => void
}) {
  const preview = action.preview as { to?: string; body?: string; language?: string }
  const id = `draft-${action.kind}`
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-[13px] font-medium">
        Reply to {preview.to}
        {preview.language && ` · ${preview.language.toUpperCase()}`}
        {inReview && <span className="font-normal text-muted-fg"> · you can edit it</span>}
      </label>
      <textarea
        id={id}
        rows={7}
        readOnly={!inReview}
        value={review.draft ?? preview.body ?? ''}
        onChange={(e) => onReview({ ...review, draft: e.target.value })}
        maxLength={10_000}
        className="field-sizing-content min-h-36 w-full resize-y rounded-sm bg-well px-3.5 py-3 leading-[1.55] outline-none focus-visible:outline-2 focus-visible:outline-review read-only:text-muted-fg"
      />
    </div>
  )
}

function Triaging({ message }: { message: MessageDetail }) {
  return (
    <div className="flex flex-col gap-2.5">
      <span className="font-medium">Triaging…</span>
      {message.attempts > 0 && message.error ? (
        <RetryNote message={message} />
      ) : (
        <div aria-hidden className="flex animate-pulse flex-col gap-2.5">
          <span className="block h-3 w-4/5 rounded-xs bg-well" />
          <span className="block h-3 w-3/5 rounded-xs bg-well" />
          <span className="block h-3 w-[70%] rounded-xs bg-well" />
        </div>
      )}
    </div>
  )
}

function RetryNote({ message }: { message: MessageDetail }) {
  const at = message.next_attempt_at ? ` Next try at ${clock(message.next_attempt_at)}.` : ''
  return (
    <p className="max-w-180 text-[13px] text-warn">
      Attempt {message.attempts} failed: {message.error}.{at}
    </p>
  )
}

function DeadLetter({ message }: { message: MessageDetail }) {
  const retry = useDecision(message.id)
  const done = message.actions.filter((a) => a.status === 'done' && a.kind !== 'mark_processed')
  return (
    <div role="alert" className="flex max-w-180 flex-wrap items-start gap-3 rounded-sm bg-danger-soft px-4 py-3">
      <div className="flex min-w-0 flex-[1_1_300px] flex-col gap-1">
        <span className="font-semibold text-danger">Permanent error · moved to dead letters</span>
        {message.error && <code className="font-mono text-xs break-words">{message.error}</code>}
        <span className="text-[13px] opacity-75">
          {done.length > 0
            ? `${joinTitles(done)} already ${done.length === 1 ? 'exists' : 'exist'} and won't be created twice on retry.`
            : 'Nothing was created yet, so a retry starts clean.'}
        </span>
        {retry.error && <span className="text-[13px] text-danger">{retry.error.message}</span>}
      </div>
      <Button variant="primary" disabled={retry.isPending} onClick={() => retry.mutate({ action: 'retry' })}>
        Retry
      </Button>
    </div>
  )
}

function joinTitles(actions: ActionOut[]): string {
  const names = actions.map((a) => `the ${ACTION_TITLE[a.kind].replace(/^Gmail reply draft$/, 'reply draft')}`)
  const text = names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names.at(-1)}` : names[0]
  return text.charAt(0).toUpperCase() + text.slice(1)
}
