import type { Tone } from '@/lib/present'

import { Dot } from '../Status'

export interface Bar {
  key: string
  label: string
  value: number
  tone?: Tone // a status dot next to the label; the bar keeps the one chart hue
}

/**
 * A horizontal bar chart that is also its own table: label, bar, value per row.
 * One hue for every bar (magnitude, not identity); thin bars, square at the
 * baseline and rounded at the tip; the value sits at the tip in text color.
 * Hover or focus a row for its share of the total.
 */
export function BarList({ rows, total, unit }: { rows: Bar[]; total: number; unit: string }) {
  const max = Math.max(1, ...rows.map((row) => row.value))
  return (
    <table className="w-full border-separate border-spacing-y-1">
      <thead className="sr-only">
        <tr>
          <th scope="col">Name</th>
          <th scope="col">Share</th>
          <th scope="col">Count</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const share = total ? Math.round((row.value / total) * 100) : 0
          const tip = `${row.value} ${row.value === 1 ? unit : `${unit}s`} · ${share}% of ${total}`
          return (
            <tr key={row.key} tabIndex={0} className="group outline-none">
              <th
                scope="row"
                className="w-px py-1 pr-4 text-left font-normal whitespace-nowrap group-hover:text-fg group-focus-visible:underline"
              >
                <span className="flex items-center gap-2">
                  {row.tone && <Dot tone={row.tone} />}
                  {row.label}
                </span>
              </th>
              <td className="relative py-1">
                <span className="sr-only">{share}%</span>
                <span
                  aria-hidden
                  className="block h-3 rounded-r-[4px] bg-bar transition-opacity group-hover:opacity-80 group-focus-visible:opacity-80"
                  style={{ width: row.value ? `max(2px, ${(row.value / max) * 100}%)` : 0 }}
                />
                <span
                  role="tooltip"
                  className="pointer-events-none absolute bottom-full left-0 z-10 mb-1 hidden rounded-xs bg-fg px-2 py-1 text-xs whitespace-nowrap text-page group-hover:block group-focus-visible:block"
                >
                  {tip}
                </span>
              </td>
              <td className="w-px py-1 pl-3 text-right font-mono text-[13px] tabular-nums">{row.value}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
