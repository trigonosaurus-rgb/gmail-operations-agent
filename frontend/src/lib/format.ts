const LOCALE = 'en-GB' // 24-hour clock and "12 Oct": unambiguous for readers anywhere

const time = new Intl.DateTimeFormat(LOCALE, { hour: '2-digit', minute: '2-digit' })
const timeSec = new Intl.DateTimeFormat(LOCALE, {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})
const day = new Intl.DateTimeFormat(LOCALE, { day: 'numeric', month: 'short' })
const dayYear = new Intl.DateTimeFormat(LOCALE, { day: 'numeric', month: 'short', year: 'numeric' })

/** "09:42" today, "12 Oct" earlier this year, "12 Oct 2025" before that. */
export function shortWhen(iso: string | null | undefined, now = new Date()): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (date.toDateString() === now.toDateString()) return time.format(date)
  return (date.getFullYear() === now.getFullYear() ? day : dayYear).format(date)
}

/** "12 Oct, 09:42" — for the detail header, where the day matters too. */
export function fullWhen(iso: string | null | undefined, now = new Date()): string {
  if (!iso) return ''
  const date = new Date(iso)
  const clock = time.format(date)
  return date.toDateString() === now.toDateString() ? `today, ${clock}` : `${shortWhen(iso, now)}, ${clock}`
}

export function clock(iso: string): string {
  return timeSec.format(new Date(iso))
}

export function money(usd: number | null | undefined): string {
  if (usd == null) return '—'
  if (usd === 0) return '$0'
  if (usd < 0.001) return `$${usd.toFixed(5)}`
  if (usd < 1) return `$${usd.toFixed(4)}`
  return `$${usd.toFixed(2)}`
}

export function seconds(ms: number | null | undefined): string {
  if (ms == null) return '—'
  return `${(ms / 1000).toFixed(1)} s`
}

export function count(n: number): string {
  return n.toLocaleString('en-US')
}
