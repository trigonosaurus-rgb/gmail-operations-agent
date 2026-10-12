import { describe, expect, it } from 'vitest'

import { money, seconds, shortWhen } from './format'

describe('format', () => {
  const now = new Date(2026, 9, 12, 15, 0)

  it('shows the time for today and the day otherwise', () => {
    expect(shortWhen(new Date(2026, 9, 12, 9, 42).toISOString(), now)).toBe('09:42')
    expect(shortWhen(new Date(2026, 9, 11, 9, 42).toISOString(), now)).toBe('11 Oct')
    expect(shortWhen(new Date(2025, 9, 11, 9, 42).toISOString(), now)).toBe('11 Oct 2025')
    expect(shortWhen(null, now)).toBe('')
  })

  it('keeps tiny model costs readable', () => {
    expect(money(0.0001087)).toBe('$0.00011')
    expect(money(0.0123)).toBe('$0.0123')
    expect(money(4.5)).toBe('$4.50')
    expect(money(null)).toBe('—')
    expect(seconds(2230)).toBe('2.2 s')
  })
})
