import { PaperclipIcon } from 'lucide-react'

import type { MessageDetail, StatusOut } from '@/api/types'
import { clock, count, fullWhen, money, seconds } from '@/lib/format'
import { eventText } from '@/lib/present'

export function OriginalTab({ message }: { message: MessageDetail }) {
  const { email } = message
  return (
    <div className="flex flex-col gap-3">
      <span className="text-[13px] text-muted-fg">
        From {message.sender_name} &lt;{message.sender_address}&gt; · to {email.to || '—'}
        {email.reply_to && <> · reply-to {email.reply_to}</>} · received{' '}
        {fullWhen(message.received_at ?? message.created_at)}
      </span>
      <pre className="rounded-sm bg-well p-4 font-sans leading-relaxed break-words whitespace-pre-wrap">
        {email.body || '(empty)'}
      </pre>
      <span className="text-[13px] text-muted-fg">
        The cleaned text the model saw
        {email.body_truncated && ', cut to the length limit'}
        {email.is_automated && '. Sent by an automated system, so no reply draft is made'}.
      </span>
      {email.attachments.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {email.attachments.map((name) => (
            <li key={name} className="flex items-center gap-1.5 rounded-sm bg-well px-2.5 py-1 text-[13px]">
              <PaperclipIcon className="size-3.5 text-muted-fg" />
              {name}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function ActivityTab({ message, source }: { message: MessageDetail; source: StatusOut['source'] }) {
  const lines = message.events
    .map((event) => ({ id: event.id, at: event.created_at, text: eventText(event, source) }))
    .filter((line) => line.text)
  const usage = message.usage
  return (
    <div className="flex flex-wrap gap-6">
      <ol className="flex flex-[1_1_280px] flex-col gap-3">
        {lines.map((line) => (
          <li key={line.id} className="flex gap-3">
            <time dateTime={line.at} className="min-w-16 font-mono text-xs leading-5 text-muted-fg">
              {clock(line.at)}
            </time>
            <span className="min-w-0 break-words">{line.text}</span>
          </li>
        ))}
      </ol>
      {usage && (
        <dl className="grid flex-[1_1_220px] grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 self-start rounded-md bg-well p-4 text-[13px] [&_dd]:font-mono [&_dt]:text-muted-fg">
          <dt>Model</dt>
          <dd>{usage.model}</dd>
          <dt>Tokens</dt>
          <dd>
            {count(usage.input_tokens)} in · {count(usage.output_tokens)} out
          </dd>
          <dt>Cached</dt>
          <dd>{count(usage.cached_tokens)}</dd>
          <dt>Latency</dt>
          <dd>{seconds(usage.latency_ms)}</dd>
          <dt>Cost</dt>
          <dd>{money(usage.cost_usd)}</dd>
          {usage.recorded && (
            <dd className="col-span-2 mt-1 font-sans! text-xs text-muted-fg">
              Replayed from a recorded run of this email, so the demo costs nothing here.
            </dd>
          )}
        </dl>
      )}
    </div>
  )
}
