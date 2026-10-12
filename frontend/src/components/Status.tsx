import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'
import { TONE_BG, TONE_TEXT, type Tone } from '@/lib/present'

/** Status language: small monospace capitals, optionally led by a colored dot. */
export function Caps({
  tone = 'muted',
  dot = false,
  className,
  children,
}: {
  tone?: Tone
  dot?: boolean
  className?: string
  children: ReactNode
}) {
  return (
    <span className={cn('caps inline-flex items-center gap-1.5', TONE_TEXT[tone], className)}>
      {dot && <Dot tone={tone} />}
      {children}
    </span>
  )
}

export function Dot({ tone, className }: { tone: Tone; className?: string }) {
  return <span aria-hidden className={cn('size-1.5 shrink-0 rounded-full', TONE_BG[tone], className)} />
}
