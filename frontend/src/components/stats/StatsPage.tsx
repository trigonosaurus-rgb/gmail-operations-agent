import { getRouteApi } from '@tanstack/react-router'

import { useStats, useStatus } from '@/api/queries'
import type { Category, MessageState, StatsOut } from '@/api/types'
import { count, money, seconds } from '@/lib/format'
import { CATEGORY, STATE, type Tone } from '@/lib/present'
import { cn } from '@/lib/utils'
import { RANGES, type Hours } from '@/router'

import { BarList } from './BarList'

const route = getRouteApi('/stats')

const RANGE_LABEL: Record<Hours, string> = { 24: '24 hours', 168: '7 days', 720: '30 days' }
const PIPELINE: MessageState[] = ['new', 'awaiting_approval', 'acting', 'done', 'rejected', 'dead']

export function StatsPage() {
  const { hours = 24 } = route.useSearch()
  const stats = useStats(hours)
  const model = useStatus().data?.model

  return (
    <main className="flex-1 px-6 pt-5 pb-10 max-lg:px-4 lg:overflow-y-auto">
      <div className="mx-auto flex max-w-260 flex-col gap-4">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <h1 className="text-[22px] font-semibold tracking-[-0.015em]">Stats</h1>
          <RangePicker hours={hours} />
          <p className="basis-full text-[13px] text-muted-fg">
            Mail that arrived in the last {RANGE_LABEL[hours]} and where it stands now. The inbox
            tabs count everything, whenever it arrived.
          </p>
        </div>
        {stats.isPending ? (
          <p className="text-muted-fg">Loading…</p>
        ) : stats.isError ? (
          <p className="text-danger">Could not load stats: {stats.error.message}</p>
        ) : (
          <div className={cn('transition-opacity', stats.isPlaceholderData && 'opacity-60')}>
            <Report stats={stats.data} model={model} />
          </div>
        )}
      </div>
    </main>
  )
}

function RangePicker({ hours }: { hours: Hours }) {
  const navigate = route.useNavigate()
  return (
    <div role="radiogroup" aria-label="Period" className="flex gap-0.5">
      {RANGES.map((range) => (
        <button
          key={range}
          type="button"
          role="radio"
          aria-checked={range === hours}
          onClick={() => void navigate({ search: { hours: range === 24 ? undefined : range }, replace: true })}
          className={cn(
            'min-h-8 rounded-sm px-3 text-[13px] font-medium',
            range === hours ? 'bg-field text-fg' : 'text-muted-fg hover:text-fg',
          )}
        >
          {RANGE_LABEL[range]}
        </button>
      ))}
    </div>
  )
}

function Report({ stats, model }: { stats: StatsOut; model?: string }) {
  const { counts, llm } = stats
  const total = counts.all ?? 0
  if (total === 0) {
    return (
      <section className="rounded-lg bg-panel p-10 text-center text-muted-fg">
        No mail arrived in the last {RANGE_LABEL[stats.hours as Hours] ?? `${stats.hours} hours`}.
      </section>
    )
  }

  const states = PIPELINE.map((state) => ({
    key: state,
    label: STATE[state].label,
    value: counts[state] ?? 0,
    tone: STATE[state].tone as Tone,
  }))
  const categories = Object.entries(stats.by_category)
    .map(([key, value]) => ({ key, label: CATEGORY[key as Category] ?? key, value }))
    .filter((row) => row.value > 0)
    .sort((a, b) => b.value - a.value)

  return (
    <section aria-label="Report" className="flex flex-col rounded-lg bg-panel">
      <dl className="grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-x-6 gap-y-5 p-6 max-sm:p-4">
        <Kpi label="Emails" value={count(total)} />
        <Kpi label="Needs review" value={count(counts.awaiting_approval ?? 0)} />
        <Kpi label="Dead letters" value={count(counts.dead ?? 0)} tone={counts.dead ? 'danger' : undefined} />
        <Kpi
          label="Model spend"
          value={money(llm.cost_usd)}
          note={llm.cost_per_1k_usd != null ? `$${llm.cost_per_1k_usd.toFixed(2)} per 1,000 emails` : undefined}
        />
        <Kpi
          label="Median triage"
          value={seconds(llm.latency_ms.p50)}
          note={llm.latency_ms.p95 != null ? `95th percentile ${seconds(llm.latency_ms.p95)}` : undefined}
        />
      </dl>

      <div className="grid gap-x-10 gap-y-8 border-t p-6 max-sm:p-4 md:grid-cols-2">
        <Chart title="Where mail stands" caption="Emails by state, from arrival to done">
          <BarList rows={states} total={total} unit="email" />
        </Chart>
        <Chart title="What came in" caption="Emails by category the model assigned">
          {categories.length ? (
            <BarList rows={categories} total={total} unit="email" />
          ) : (
            <p className="text-muted-fg">Nothing triaged yet.</p>
          )}
        </Chart>
      </div>

      <dl className="flex flex-wrap gap-x-10 gap-y-3 border-t px-6 py-4 text-[13px] max-sm:px-4 [&_dd]:font-mono [&_dt]:text-muted-fg [&>div]:flex [&>div]:gap-2">
        {model && (
          <div>
            <dt>Model</dt>
            <dd>{model}</dd>
          </div>
        )}
        <div>
          <dt>Calls</dt>
          <dd>{count(llm.calls)}</dd>
        </div>
        <div>
          <dt>Failed calls</dt>
          <dd className={cn(llm.failures > 0 && 'text-danger')}>{count(llm.failures)}</dd>
        </div>
        <div>
          <dt>Average latency</dt>
          <dd>{seconds(llm.latency_ms.avg)}</dd>
        </div>
      </dl>
    </section>
  )
}

function Kpi({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: 'danger' }) {
  return (
    <div className="flex flex-col gap-1">
      <dt className="text-[13px] text-muted-fg">{label}</dt>
      <dd className={cn('text-[28px] leading-none font-semibold tracking-[-0.02em] tabular-nums', tone === 'danger' && 'text-danger')}>
        {value}
      </dd>
      {note && <dd className="text-xs text-muted-fg">{note}</dd>}
    </div>
  )
}

function Chart({ title, caption, children }: { title: string; caption: string; children: React.ReactNode }) {
  return (
    <figure className="flex min-w-0 flex-col gap-3">
      <figcaption className="flex flex-col">
        <span className="font-semibold">{title}</span>
        <span className="text-[13px] text-muted-fg">{caption}</span>
      </figcaption>
      {children}
    </figure>
  )
}
