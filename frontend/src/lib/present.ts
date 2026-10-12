/** How domain values read and look in the UI. Pure functions; covered by present.test.ts. */
import type { LiveState } from '@/api/live'
import type {
  ActionKind,
  ActionOut,
  Category,
  EventOut,
  MessageState,
  MessageSummary,
  Priority,
  Risk,
  StatusOut,
} from '@/api/types'

import { clock } from './format'

export type Tone = 'muted' | 'review' | 'ok' | 'warn' | 'danger' | 'fg'

/** Text color classes per tone. Kept literal so Tailwind sees them. */
export const TONE_TEXT: Record<Tone, string> = {
  muted: 'text-muted-fg',
  review: 'text-review',
  ok: 'text-ok',
  warn: 'text-warn',
  danger: 'text-danger',
  fg: 'text-fg',
}
export const TONE_BG: Record<Tone, string> = {
  muted: 'bg-muted-fg',
  review: 'bg-review',
  ok: 'bg-ok',
  warn: 'bg-warn',
  danger: 'bg-danger',
  fg: 'bg-fg',
}

export const CATEGORY: Record<Category, string> = {
  lead: 'Lead',
  client: 'Client',
  support: 'Support',
  invoice: 'Invoice',
  meeting: 'Meeting',
  newsletter: 'Newsletter',
  notification: 'Notification',
  personal: 'Personal',
  spam: 'Spam',
  other: 'Other',
}

export const PRIORITY: Record<Priority, string> = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  urgent: 'Urgent',
}

/** Priority is told apart by words; color flags only "urgent". */
export const PRIORITY_TONE: Record<Priority, Tone> = {
  low: 'muted',
  medium: 'muted',
  high: 'fg',
  urgent: 'danger',
}

/** Low and medium are the norm, so the list mentions priority only when it is high or urgent. */
export function notablePriority(priority: Priority | null): priority is 'high' | 'urgent' {
  return priority === 'high' || priority === 'urgent'
}

export const RISK: Record<Risk, string> = {
  none: 'None',
  spam: 'Spam',
  phishing: 'Phishing',
  prompt_injection: 'Prompt injection',
}

export const RISK_TITLE: Record<Exclude<Risk, 'none'>, string> = {
  spam: 'Spam',
  phishing: 'Phishing suspected',
  prompt_injection: 'Prompt injection detected',
}

export function isRisky(risk: Risk | null): risk is Exclude<Risk, 'none'> {
  return risk != null && risk !== 'none'
}

export const STATE: Record<MessageState, { label: string; tone: Tone }> = {
  new: { label: 'Triaging', tone: 'muted' },
  awaiting_approval: { label: 'Needs review', tone: 'review' },
  acting: { label: 'Running', tone: 'review' },
  done: { label: 'Done', tone: 'ok' },
  rejected: { label: 'Rejected', tone: 'muted' },
  dead: { label: 'Dead letter', tone: 'danger' },
}

/** The state as shown: work that failed and waits for another attempt reads "Retrying". */
export function stateOf(message: Pick<MessageSummary, 'state' | 'attempts'>): {
  label: string
  tone: Tone
} {
  const working = message.state === 'new' || message.state === 'acting'
  return working && message.attempts > 0 ? { label: 'Retrying', tone: 'warn' } : STATE[message.state]
}

// --- actions -----------------------------------------------------------------------

export const ACTION_TITLE: Record<ActionKind, string> = {
  notion_task: 'Notion task',
  sheets_row: 'Sheets log row',
  gmail_draft: 'Gmail reply draft',
  mark_processed: 'Gmail label',
}

export type Mark = 'review' | 'queued' | 'running' | 'done' | 'failed' | 'skipped' | 'notrun'

export const MARK: Record<Mark, { label: string; tone: Tone }> = {
  review: { label: 'Needs approval', tone: 'review' },
  queued: { label: 'Queued', tone: 'muted' },
  running: { label: 'Running', tone: 'review' },
  done: { label: 'Done', tone: 'ok' },
  failed: { label: 'Failed', tone: 'danger' },
  skipped: { label: 'Skipped', tone: 'muted' },
  notrun: { label: 'Not run yet', tone: 'muted' },
}

/** Whether a person can leave this action out when approving. The label always runs. */
export function canSkip(kind: ActionKind): boolean {
  return kind !== 'mark_processed'
}

export function actionMark(action: ActionOut, state: MessageState, skippedHere = false): Mark {
  if (state === 'awaiting_approval') {
    if (skippedHere) return 'skipped'
    return action.needs_approval ? 'review' : 'queued'
  }
  switch (action.status) {
    case 'done':
      return 'done'
    case 'failed':
      return 'failed'
    case 'running':
      return 'running'
    case 'skipped':
      return 'skipped'
    case 'pending':
      return state === 'dead' ? 'notrun' : 'queued'
  }
}

const NOTE: Record<ActionKind, Partial<Record<Mark, string>>> = {
  notion_task: {
    review: 'Created in your Notion tasks database when you approve.',
    queued: 'Created in Notion.',
    running: 'Creating the task now.',
    done: 'Created in Notion.',
    failed: 'Notion rejected the request.',
    skipped: 'Skipped: no task is created.',
  },
  sheets_row: {
    queued: 'Appended to the Inbox log sheet as plain text (RAW), so formulas in a subject never run.',
    done: 'Appended to the Inbox log sheet as plain text (RAW).',
    skipped: 'Skipped: no log row.',
  },
  gmail_draft: {
    review: 'Saved as a draft in the same thread when you approve. Never sent automatically.',
    queued: 'Saved as a draft in the same thread. Never sent automatically.',
    done: 'Saved as a draft in the thread. Waiting for you in Gmail, not sent.',
    skipped: 'Skipped: no draft.',
  },
  mark_processed: {
    review: 'Applied last: Agent/Processed marks the email as handled. Unread status is left alone.',
    queued: 'Applied last: Agent/Processed marks the email as handled. Unread status is left alone.',
    done: 'Labelled Agent/Processed. Unread status left alone.',
    notrun: 'Applied only after every other action succeeds.',
  },
}

export function actionNote(kind: ActionKind, mark: Mark): string {
  return NOTE[kind][mark] ?? ''
}

// --- activity ----------------------------------------------------------------------

const ACTION_DONE: Record<ActionKind, string> = {
  notion_task: 'Notion task created',
  sheets_row: 'Sheets row appended',
  gmail_draft: 'Gmail draft saved',
  mark_processed: 'Labelled Agent/Processed',
}

type Data = Record<string, unknown>

const ACTION_ERROR = /^(notion_task|sheets_row|gmail_draft|mark_processed):/

function by(data: Data): string {
  const who = typeof data.by === 'string' ? data.by : 'you'
  return who === 'you' ? 'you' : `the ${who}`
}

function kind(data: Data): ActionKind {
  return data.kind as ActionKind
}

/** One line of the activity log, or null for events that only add noise there. */
export function eventText(event: EventOut, source: StatusOut['source'] = 'gmail'): string | null {
  const data = event.data as Data
  switch (event.type) {
    case 'ingested':
      return source === 'demo' ? 'Arrived in the demo inbox' : 'Fetched from Gmail'
    case 'triaged': {
      const parts = [CATEGORY[data.category as Category], data.priority].join(', ').toLowerCase()
      const risk = data.risk as Risk
      return `Triaged · ${parts}${isRisky(risk) ? ` · risk ${RISK[risk].toLowerCase()}` : ''}`
    }
    case 'awaiting_approval':
      return 'Waiting for your approval'
    case 'approved':
      return `Approved by ${by(data)}`
    case 'rejected':
      return data.by ? `Rejected by ${by(data)}` : 'Finished: labelled as handled, nothing else done'
    case 'action_started':
      return null // the outcome line follows right after
    case 'action_done':
      return ACTION_DONE[kind(data)] ?? `${data.kind} done`
    case 'action_failed':
      return `${ACTION_TITLE[kind(data)] ?? data.kind} failed: ${String(data.error ?? '')}`
    case 'action_recovered':
      return `${ACTION_TITLE[kind(data)] ?? data.kind} had already succeeded before a restart: not repeated`
    case 'retry_scheduled': {
      const at = typeof data.next_attempt_at === 'string' ? ` at ${clock(data.next_attempt_at)}` : ''
      return `Attempt ${String(data.attempt)} failed, retrying${at}: ${String(data.error ?? '')}`
    }
    case 'retry_requested':
      return 'Retry requested'
    case 'dead':
      // An action's error is already on its own "failed" line just above.
      return typeof data.error === 'string' && !ACTION_ERROR.test(data.error)
        ? `Moved to dead letters: ${data.error}`
        : 'Moved to dead letters'
    case 'done':
      return 'Done'
    default:
      return event.type.replaceAll('_', ' ')
  }
}

// --- connection --------------------------------------------------------------------

export interface Health {
  label: string
  tone: Tone
  detail: string
}

// Keys are BlockedError.service names from the backend.
const SERVICE: Record<string, string> = { google: 'Google', notion: 'Notion', openai: 'OpenAI', budget: 'Budget' }

export function health(status: StatusOut | undefined, live: LiveState): Health {
  if (live === 'offline') return { label: 'Offline', tone: 'danger', detail: 'Lost the connection to the agent. Reload the page.' }
  if (!status || live === 'connecting') return { label: 'Connecting…', tone: 'muted', detail: '' }
  const { worker } = status
  if (!worker.running) return { label: 'Agent stopped', tone: 'danger', detail: 'The worker is not running: new mail waits.' }
  if (worker.blocked) {
    const name = SERVICE[worker.blocked.service] ?? worker.blocked.service
    const until = worker.blocked.until ? ` Resumes at ${clock(worker.blocked.until)}.` : ''
    return { label: `${name} paused`, tone: 'warn', detail: `${worker.blocked.reason}.${until}` }
  }
  if (worker.last_error) return { label: 'Last poll failed', tone: 'warn', detail: worker.last_error }
  return { label: 'All connected', tone: 'ok', detail: '' }
}

export function connectionLines(status: StatusOut): { name: string; on: boolean; text: string }[] {
  return ['gmail', 'notion', 'sheets'].map((key) => {
    const c = status.connections[key]
    const on = !!c?.enabled
    let text = on ? 'connected' : 'off'
    if (on && c.sandbox) text = key === 'gmail' ? 'synthetic inbox' : 'sandbox'
    else if (on && key === 'gmail') text = 'polling'
    return { name: SERVICE[key], on, text }
  })
}
