import { Link } from '@tanstack/react-router'

import type { MessageSummary } from '@/api/types'
import { shortWhen } from '@/lib/format'
import {
  CATEGORY,
  isRisky,
  notablePriority,
  PRIORITY,
  PRIORITY_TONE,
  RISK,
  stateOf,
} from '@/lib/present'
import { cn } from '@/lib/utils'

import { Caps } from '../Status'

export function MessageRow({ message, selected }: { message: MessageSummary; selected: boolean }) {
  const state = stateOf(message)
  return (
    <li className="border-t py-[3px]">
      <Link
        from="/"
        to="/"
        search={(s) => ({ ...s, m: message.id })}
        aria-current={selected ? 'true' : undefined}
        className={cn(
          'flex flex-col gap-1.5 rounded-md p-3 text-fg no-underline',
          selected ? 'bg-field' : 'hover:bg-field/50',
        )}
      >
        <span className="flex items-center gap-2">
          <span className="min-w-0 flex-1 truncate font-semibold">
            {message.sender_name || message.sender_address}
          </span>
          <span className="text-xs text-muted-fg">
            {shortWhen(message.received_at ?? message.created_at)}
          </span>
        </span>
        <span className="truncate">{message.subject || '(no subject)'}</span>
        {message.summary && (
          <span className="line-clamp-2 text-[13px] leading-[1.45] text-muted-fg">
            {message.summary}
          </span>
        )}
        <span className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1">
          {notablePriority(message.priority) && (
            <Caps tone={PRIORITY_TONE[message.priority]}>{PRIORITY[message.priority]} priority</Caps>
          )}
          {message.category && <Caps>{CATEGORY[message.category]}</Caps>}
          <Caps tone={state.tone} dot>
            {state.label}
          </Caps>
          {isRisky(message.risk) && <Caps tone="warn">Risk · {RISK[message.risk]}</Caps>}
        </span>
      </Link>
    </li>
  )
}
