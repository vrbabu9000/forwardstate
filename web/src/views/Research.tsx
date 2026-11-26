import { useEffect, useId, useMemo, useState } from 'react'
import { useParams } from 'react-router'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import {
  useAnalysts,
  useEvents,
  useForecast,
  useFundamentals,
  useImpact,
  useMacro,
  usePeers,
  usePrices,
  useSecurities,
  useSettings,
  useSources,
} from '../api/hooks'
import type { Event, ForecastRequest, Horizon, ScenarioAssumptions, SecurityForecast } from '../api/types'
import { asOfDateToIso } from '../lib/asof'
import { DASH, day, dateTime, num, pct, price, signed, titleCase } from '../lib/format'
import { useApp } from '../state/app'
import PriceChart from '../components/charts/PriceChart'
import FanChart from '../components/charts/FanChart'
import PeerChart, { peerColor } from '../components/charts/PeerChart'
import { MARKER_LABEL, MARKER_VAR, eventDate, markerClass, type MarkerClass } from '../components/charts/eventStyle'
import {
  ConfidenceBadge,
  Dot,
  ErrorBox,
  Label,
  Loading,
  OriginBadge,
  Panel,
  ProvenanceButton,
  StatusNotice,
} from '../components/ui'

const HORIZON_LABEL: Record<Horizon, string> = { short: 'Short term', medium: 'Medium term', long: 'Long term' }

function yearsBefore(d: string, years: number): string {
  const x = new Date(`${d}T12:00:00Z`)
  x.setUTCFullYear(x.getUTCFullYear() - years)
  return x.toISOString().slice(0, 10)
}

function useAnchorDate(asOf: string | null): string {
  const { data } = useSources()
  const latest = data?.find((s) => s.source_id === 'yahoo')?.latest_record_date ?? undefined
  return asOf ?? latest ?? new Date().toISOString().slice(0, 10)
}

// ------------------------------------------------------------------ event detail

export function ImpactTable({ eventId }: { eventId: string }) {
  const { asOf } = useApp()
  const q = useImpact(eventId, asOf)
  if (q.isLoading) return <Loading label="Loading impact estimates" />
  if (q.error) return <ErrorBox error={q.error} />
  const rows = q.data ?? []
  if (!rows.length) return <p className="text-sm text-muted">No impact estimates for this event.</p>
  return (
    <div className="space-y-2">
      <div className="scroll-x">
        <table className="data text-xs">
          <thead>
            <tr>
              <th>Security</th>
              <th>Type</th>
              <th className="num">CAR</th>
              <th className="num">t-stat</th>
              <th className="num">Forward est.</th>
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.security_id}-${r.realized}`}>
                <td className="font-semibold">{r.security_id}</td>
                <td>{r.realized ? 'Realized' : 'Forward'}</td>
                <td className="num">{pct(r.abnormal_return, true)}</td>
                <td className="num">{num(r.t_stat, 2)}</td>
                <td className="num">
                  {r.expected_return_impact != null ? `${pct(r.expected_return_impact, true)} ± ${pct(r.uncertainty)}` : DASH}
                </td>
                <td>
                  <ConfidenceBadge value={r.confidence} prefix="" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-muted">
        CAR is the cumulative abnormal return versus {rows[0].benchmark_id ?? 'the benchmark'} from {rows[0].window_pre_days} day before to{' '}
        {rows[0].window_post_days} days after. Association, not causation.
        {rows.some((r) => r.confidence === 'unavailable') ? ` ${rows.find((r) => r.confidence === 'unavailable')?.note ?? ''}` : ''}
      </p>
    </div>
  )
}

export function EventDetail({ event, onClose }: { event: Event; onClose?: () => void }) {
  const cls = markerClass(event)
  return (
    <div className="space-y-3" aria-live="polite">
      <div className="flex items-start gap-2">
        <Dot color={`var(${MARKER_VAR[cls]})`} />
        <div className="min-w-0 flex-1">
          <h3 className="text-sm leading-snug font-semibold">{event.title}</h3>
          <p className="text-xs text-muted">
            {MARKER_LABEL[cls]} · {titleCase(event.subtype)} · {event.scope} · {event.status}
          </p>
        </div>
        <OriginBadge origin={event.origin} />
        {onClose ? (
          <button type="button" className="btn btn-quiet text-xs" onClick={onClose}>
            Close
          </button>
        ) : null}
      </div>
      <dl className="grid grid-cols-[7rem_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-muted">When</dt>
        <dd>{dateTime(event.occurred_at ?? event.scheduled_at)}</dd>
        <dt className="text-muted">Known from</dt>
        <dd>
          {dateTime(event.available_at)}
          {event.availability_inferred ? ' (inferred)' : ''}
        </dd>
        {event.expected_outcome ? (
          <>
            <dt className="text-muted">Expected</dt>
            <dd>{event.expected_outcome}</dd>
          </>
        ) : null}
        <dt className="text-muted">Outcome</dt>
        <dd>{event.actual_outcome ?? (event.status === 'upcoming' ? 'Not yet known' : DASH)}</dd>
        {event.surprise != null ? (
          <>
            <dt className="text-muted">Surprise</dt>
            <dd>{signed(event.surprise)}</dd>
          </>
        ) : null}
        <dt className="text-muted">Affects</dt>
        <dd>{(event.affected_security_ids ?? []).join(', ') || DASH}</dd>
        {event.canonical_event_id ? (
          <>
            <dt className="text-muted">Duplicate of</dt>
            <dd>{event.canonical_event_id}</dd>
          </>
        ) : null}
        <dt className="text-muted">Source</dt>
        <dd className="break-all">{event.source_ids?.join(', ') || event.source_id}</dd>
      </dl>
      <ImpactTable eventId={event.event_id} />
    </div>
  )
}

// ------------------------------------------------------------------ price + events

function PricePanel({ securityId, anchor }: { securityId: string; anchor: string }) {
  const { asOf } = useApp()
  const [years, setYears] = useState(3)
  const start = yearsBefore(anchor, years)
  const prices = usePrices(securityId, asOf, start)
  const events = useEvents({ security_id: securityId, start }, asOf)
  const [selected, setSelected] = useState<Event | null>(null)
  const [hidden, setHidden] = useState<Set<MarkerClass>>(new Set())
  useEffect(() => setSelected(null), [securityId])

  const shown = useMemo(() => (events.data ?? []).filter((e) => !hidden.has(markerClass(e)) && !e.canonical_event_id), [events.data, hidden])
  const counts = useMemo(() => {
    const c: Record<MarkerClass, number> = { scheduled: 0, anticipated: 0, unexpected: 0, derived: 0 }
    for (const e of events.data ?? []) if (!e.canonical_event_id) c[markerClass(e)]++
    return c
  }, [events.data])
  const recent = [...shown].reverse().slice(0, 40)

  return (
    <Panel
      id="price"
      title="Price history and events"
      description="Adjusted close. Markers show events by class; pick one to see details."
      aside={
        <>
          <OriginBadge origin={prices.data?.origin} />
          <div role="group" aria-label="Range" className="flex overflow-hidden rounded border border-line-strong">
            {[1, 3, 5].map((y) => (
              <button
                key={y}
                type="button"
                aria-pressed={years === y}
                onClick={() => setYears(y)}
                className={`px-2.5 py-1 text-xs font-semibold ${years === y ? 'bg-accent text-accent-ink' : 'hover:bg-surface-2'}`}
              >
                {y}Y
              </button>
            ))}
          </div>
        </>
      }
    >
      <div className="mb-2 flex flex-wrap gap-1.5" role="group" aria-label="Show event classes">
        {(Object.keys(MARKER_LABEL) as MarkerClass[]).map((c) => (
          <button
            key={c}
            type="button"
            aria-pressed={!hidden.has(c)}
            onClick={() => setHidden((h) => { const n = new Set(h); if (n.has(c)) n.delete(c); else n.add(c); return n })}
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs ${hidden.has(c) ? 'border-line text-muted line-through' : 'border-line-strong'}`}
          >
            <Dot color={`var(${MARKER_VAR[c]})`} />
            {MARKER_LABEL[c]} <span className="text-muted">{counts[c]}</span>
          </button>
        ))}
      </div>
      {prices.isLoading ? <Loading label="Loading prices" /> : null}
      <ErrorBox error={prices.error} />
      {prices.data && prices.data.points.length === 0 ? <p className="text-sm text-muted">No prices before this date.</p> : null}
      {prices.data?.points.length ? (
        <PriceChart points={prices.data.points} events={shown} onSelectEvent={setSelected} label={`${securityId} adjusted close with ${shown.length} event markers`} />
      ) : null}
      <div className="mt-3 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <div className="min-w-0">
          <h3 className="mb-1 text-xs font-semibold text-muted">Events in range, newest first</h3>
          <ul className="max-h-64 overflow-y-auto rounded border border-line">
            {recent.length === 0 ? <li className="px-3 py-2 text-sm text-muted">No events in this range.</li> : null}
            {recent.map((e) => {
              const c = markerClass(e)
              return (
                <li key={e.event_id} className="border-b border-line last:border-0">
                  <button
                    type="button"
                    onClick={() => setSelected(e)}
                    aria-pressed={selected?.event_id === e.event_id}
                    className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs ${selected?.event_id === e.event_id ? 'bg-accent-soft' : 'hover:bg-surface-2'}`}
                  >
                    <Dot color={`var(${MARKER_VAR[c]})`} />
                    <span className="w-[5.5rem] shrink-0 text-muted tabular-nums">{day(eventDate(e))}</span>
                    <span className="min-w-0 flex-1 truncate">{e.title}</span>
                    {e.status === 'upcoming' ? <span className="text-[11px] font-semibold text-warn">upcoming</span> : null}
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
        <div className="min-w-0">
          {selected ? (
            <div className="inset p-3">
              <EventDetail event={selected} onClose={() => setSelected(null)} />
            </div>
          ) : (
            <p className="inset p-3 text-sm text-muted">Pick a marker on the chart or an event in the list to see its timing, outcome and estimated impact.</p>
          )}
        </div>
      </div>
    </Panel>
  )
}

// ------------------------------------------------------------------ peers

function PeerPanel({ securityId, anchor }: { securityId: string; anchor: string }) {
  const { asOf } = useApp()
  const q = usePeers(securityId, asOf, yearsBefore(anchor, 1))
  return (
    <Panel id="peers" title="Peer comparison" description={q.data ? `Rebased to 100 on ${day(q.data.base_date)}. XLF is a benchmark, not investable.` : 'Rebased to 100.'}>
      {q.isLoading ? <Loading label="Loading peers" /> : null}
      <ErrorBox error={q.error} />
      {q.data ? (
        <>
          <PeerChart data={q.data} />
          <div className="scroll-x mt-3">
            <table className="data text-xs">
              <thead>
                <tr>
                  <th>Security</th>
                  <th className="num">Total return</th>
                  <th className="num">Volatility (yr)</th>
                  <th className="num">Max drawdown</th>
                </tr>
              </thead>
              <tbody>
                {q.data.series.map((s, i) => (
                  <tr key={s.security_id} className={s.security_id === securityId ? 'font-semibold' : ''}>
                    <td>
                      <span className="inline-flex items-center gap-2">
                        <Dot color={peerColor(i)} />
                        {s.security_id}
                        {s.security_id === 'XLF' ? <span className="font-normal text-muted">benchmark</span> : null}
                      </span>
                    </td>
                    <td className={`num ${s.total_return >= 0 ? 'text-opt' : 'text-pes'}`}>{pct(s.total_return, true)}</td>
                    <td className="num">{pct(s.volatility_annual)}</td>
                    <td className="num">{pct(-s.max_drawdown)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </Panel>
  )
}

// ------------------------------------------------------------------ fundamentals & macro

function FundamentalsPanel({ securityId, anchor }: { securityId: string; anchor: string }) {
  const { asOf } = useApp()
  const f = useFundamentals(securityId, asOf)
  const m = useMacro(asOf, yearsBefore(anchor, 3))
  const quarters = useMemo(() => {
    const by = new Map<string, { est?: number; act?: number; release?: string | null; origin?: string }>()
    for (const o of f.data ?? []) {
      const row = by.get(o.period_end) ?? {}
      if (o.metric_id === 'eps_estimate') row.est = o.value
      if (o.metric_id === 'eps_actual') { row.act = o.value; row.release = o.release_at }
      by.set(o.period_end, row)
    }
    return [...by.entries()].sort(([a], [b]) => b.localeCompare(a)).slice(0, 6)
  }, [f.data])
  const macroRows = useMemo(() => {
    const by = new Map<string, Record<string, number | string>>()
    for (const o of m.data ?? []) {
      const r = by.get(o.period_end) ?? { date: o.period_end }
      r[o.metric_id] = o.value
      by.set(o.period_end, r)
    }
    return [...by.values()].sort((a, b) => String(a.date).localeCompare(String(b.date)))
  }, [m.data])
  const latest = macroRows[macroRows.length - 1]
  const yearAgo = macroRows[Math.max(0, macroRows.length - 53)]
  const origin = f.data?.[0]?.origin ?? m.data?.[0]?.origin
  return (
    <Panel id="fund" title="Earnings and rates" aside={<OriginBadge origin={origin} />} description="EPS surprise by quarter, and US policy and Treasury rates.">
      <ErrorBox error={f.error ?? m.error} />
      <div className="grid gap-5 md:grid-cols-2">
        <div className="min-w-0">
          <h3 className="mb-1 text-xs font-semibold text-muted">EPS, last 6 reported quarters</h3>
          {f.isLoading ? <Loading /> : null}
          {quarters.length === 0 && !f.isLoading ? <p className="text-sm text-muted">No earnings data as of this date.</p> : null}
          {quarters.length ? (
            <table className="data text-xs">
              <thead>
                <tr>
                  <th>Quarter end</th>
                  <th className="num">Estimate</th>
                  <th className="num">Actual</th>
                  <th className="num">Surprise</th>
                </tr>
              </thead>
              <tbody>
                {quarters.map(([pe, r]) => {
                  const s = r.est != null && r.act != null ? r.act / r.est - 1 : null
                  return (
                    <tr key={pe}>
                      <td>{day(pe)}</td>
                      <td className="num">{price(r.est)}</td>
                      <td className="num">{r.act != null ? price(r.act) : 'Not yet reported'}</td>
                      <td className={`num ${s == null ? '' : s >= 0 ? 'text-opt' : 'text-pes'}`}>{pct(s, true)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          ) : null}
        </div>
        <div className="min-w-0">
          <h3 className="mb-1 text-xs font-semibold text-muted">Rates, percent</h3>
          {m.isLoading ? <Loading /> : null}
          {latest ? (
            <div className="mb-2 grid grid-cols-3 gap-2 text-xs">
              {(['DFF', 'DGS2', 'DGS10'] as const).map((k) => (
                <div key={k} className="inset px-2 py-1.5">
                  <div className="text-muted">{k === 'DFF' ? 'Fed funds' : k === 'DGS2' ? '2-year' : '10-year'}</div>
                  <div className="text-base font-semibold">{num(Number(latest[k]), 2)}%</div>
                  <div className="text-[11px] text-muted">
                    {signed(Number(latest[k]) - Number(yearAgo?.[k] ?? latest[k]), 2)} pts in 1y
                  </div>
                </div>
              ))}
            </div>
          ) : null}
          {macroRows.length ? (
            <div style={{ height: 140 }} role="img" aria-label="Fed funds, 2-year and 10-year Treasury yields over 3 years">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={macroRows} margin={{ top: 4, right: 6, bottom: 0, left: 0 }}>
                  <CartesianGrid vertical={false} stroke="var(--line)" />
                  <XAxis dataKey="date" tickLine={false} axisLine={{ stroke: 'var(--line)' }} minTickGap={40} tickFormatter={(d: string) => d.slice(0, 7)} />
                  <YAxis width={30} tickLine={false} axisLine={false} domain={[0, 'auto']} />
                  <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 4, fontSize: 12 }} formatter={(v, n) => [`${num(Number(v), 2)}%`, String(n)]} />
                  <Legend iconType="plainline" wrapperStyle={{ fontSize: 11 }} />
                  <Line dataKey="DFF" stroke="var(--series-1)" dot={false} strokeWidth={1.5} isAnimationActive={false} />
                  <Line dataKey="DGS2" stroke="var(--series-2)" dot={false} strokeWidth={1.5} isAnimationActive={false} />
                  <Line dataKey="DGS10" stroke="var(--series-3)" dot={false} strokeWidth={1.5} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : null}
        </div>
      </div>
    </Panel>
  )
}

// ------------------------------------------------------------------ analysts

function AnalystPanel({ securityId, lastPrice }: { securityId: string; lastPrice: number | null }) {
  const { asOf } = useApp()
  const q = useAnalysts(securityId, asOf)
  const rows = [...(q.data ?? [])].reverse().slice(0, 8)
  return (
    <Panel
      id="analysts"
      title="Analyst views"
      description="Views, not facts. Kept apart from observed data and weighted only as you choose in the assumptions."
      aside={<OriginBadge origin={rows[0]?.origin} />}
    >
      {q.isLoading ? <Loading /> : null}
      <ErrorBox error={q.error} />
      {rows.length === 0 && !q.isLoading ? <p className="text-sm text-muted">No analyst views known as of this date.</p> : null}
      <ol className="space-y-2">
        {rows.map((a) => {
          const up = a.target_price && lastPrice ? a.target_price / lastPrice - 1 : null
          return (
            <li key={a.observation_id} className="grid grid-cols-[5.5rem_1fr_auto] gap-x-3 border-b border-line pb-2 text-xs last:border-0">
              <span className="text-muted tabular-nums">{day(a.issued_at)}</span>
              <div className="min-w-0">
                <div className="font-semibold">
                  {titleCase(a.action)}
                  {a.to_rating ? ` · ${a.from_rating && a.from_rating !== a.to_rating ? `${a.from_rating} to ` : ''}${a.to_rating}` : ''}
                </div>
                <div className="truncate text-muted">{a.analyst_source}</div>
                {a.assumptions ? <div className="text-ink-2">Assumes: {a.assumptions}</div> : null}
              </div>
              <div className="text-right">
                <div className="font-semibold">{price(a.target_price)}</div>
                <div className="text-[11px] text-muted">
                  {a.prior_target_price ? `from ${price(a.prior_target_price)}` : 'target'}
                  {up != null ? ` · ${pct(up, true)} vs last` : ''}
                </div>
              </div>
            </li>
          )
        })}
      </ol>
    </Panel>
  )
}

// ------------------------------------------------------------------ scenarios

type NumKey = 'rate_change_bps' | 'earnings_surprise_pct' | 'market_return_shift_pct' | 'volatility_multiplier' | 'analyst_weight'

const ASSUMPTION_FIELDS: Array<{ key: NumKey; label: string; hint: string; step: number; min?: number; max?: number }> = [
  { key: 'rate_change_bps', label: 'Fed funds change', hint: 'bps', step: 25, min: -300, max: 300 },
  { key: 'earnings_surprise_pct', label: 'Next earnings surprise', hint: '%', step: 1, min: -50, max: 50 },
  { key: 'market_return_shift_pct', label: 'Market return shift', hint: '% a year', step: 1, min: -50, max: 50 },
  { key: 'volatility_multiplier', label: 'Volatility multiplier', hint: 'x', step: 0.1, min: 0.1, max: 5 },
  { key: 'analyst_weight', label: 'Weight on analyst targets', hint: '0 to 1', step: 0.05, min: 0, max: 1 },
]

const NEUTRAL: ScenarioAssumptions = { rate_change_bps: 0, earnings_surprise_pct: 0, market_return_shift_pct: 0, volatility_multiplier: 1, analyst_weight: 0.25, lookback_years: 5, notes: null }

function validateAssumption(key: NumKey, v: string): string | null {
  if (v.trim() === '') return 'Enter a number.'
  const n = Number(v)
  if (!Number.isFinite(n)) return 'Enter a number.'
  const f = ASSUMPTION_FIELDS.find((x) => x.key === key)!
  if (key === 'volatility_multiplier' && n <= 0) return 'Must be above 0.'
  if (f.min != null && n < f.min) return `At least ${f.min}.`
  if (f.max != null && n > f.max) return `At most ${f.max}.`
  return null
}

function AssumptionsEditor({ value, onChange, pending }: { value: ScenarioAssumptions; onChange: (a: ScenarioAssumptions) => void; pending: boolean }) {
  const base = useId()
  const [draft, setDraft] = useState<Record<NumKey, string>>(() => toDraft(value))
  useEffect(() => setDraft(toDraft(value)), [value])
  const errors = Object.fromEntries(ASSUMPTION_FIELDS.map((f) => [f.key, validateAssumption(f.key, draft[f.key])])) as Record<NumKey, string | null>

  // Re-run shortly after typing stops, only with valid values.
  useEffect(() => {
    const valid = ASSUMPTION_FIELDS.every((f) => !errors[f.key])
    if (!valid) return
    const next = { ...value, ...Object.fromEntries(ASSUMPTION_FIELDS.map((f) => [f.key, Number(draft[f.key])])) }
    if (ASSUMPTION_FIELDS.every((f) => next[f.key] === value[f.key])) return
    const t = setTimeout(() => onChange(next), 400)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft])

  return (
    <form className="space-y-3" onSubmit={(e) => e.preventDefault()} aria-label="Scenario assumptions">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {ASSUMPTION_FIELDS.map((f) => {
          const id = `${base}-${f.key}`
          return (
            <div key={f.key} className="min-w-0">
              <Label htmlFor={id} hint={f.hint}>
                {f.label}
              </Label>
              <input
                id={id}
                type="number"
                inputMode="decimal"
                step={f.step}
                min={f.min}
                max={f.max}
                className="field w-full"
                value={draft[f.key]}
                aria-invalid={!!errors[f.key]}
                aria-describedby={errors[f.key] ? `${id}-err` : undefined}
                onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
              />
              {errors[f.key] ? (
                <p id={`${id}-err`} className="mt-1 text-xs font-semibold text-danger">
                  {errors[f.key]}
                </p>
              ) : null}
            </div>
          )
        })}
      </div>
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted">
        <span aria-live="polite">{pending ? 'Updating scenarios…' : 'Scenarios update as you type.'}</span>
        <button type="button" className="btn btn-quiet text-xs" onClick={() => onChange({ ...value, ...NEUTRAL })}>
          Reset to history only
        </button>
      </div>
    </form>
  )
}

function toDraft(a: ScenarioAssumptions): Record<NumKey, string> {
  return Object.fromEntries(ASSUMPTION_FIELDS.map((f) => [f.key, String(a[f.key] ?? NEUTRAL[f.key])])) as Record<NumKey, string>
}

const SCEN_STYLE = { optimistic: 'text-opt', base: 'text-scen-base', pessimistic: 'text-pes' } as const

function HorizonCard({ f }: { f: SecurityForecast }) {
  const drivers = Object.entries(f.drivers ?? {})
  const applied = f.scenarios?.[0]?.assumptions_applied ?? []
  const has = (f.scenarios?.length ?? 0) > 0 && f.status !== 'unavailable'
  return (
    <article className="min-w-0 rounded border border-line" aria-label={`${HORIZON_LABEL[f.horizon]} forecast`}>
      <header className="flex flex-wrap items-baseline gap-2 border-b border-line px-3 py-2">
        <h3 className="text-sm font-semibold">{HORIZON_LABEL[f.horizon]}</h3>
        <span className="text-xs text-muted">{f.horizon_trading_days} market days</span>
        <span className="ml-auto">
          <ConfidenceBadge value={f.status} prefix="Status" />
        </span>
      </header>
      <div className="space-y-3 p-3">
        <StatusNotice status={f.status} reason={f.status_reason} />
        {has ? (
          <>
            <table className="data text-xs">
              <thead>
                <tr>
                  <th>Scenario</th>
                  <th className="num">Return</th>
                  <th className="num">Price</th>
                  <th className="num">80% interval</th>
                </tr>
              </thead>
              <tbody>
                {f.scenarios!.map((s) => (
                  <tr key={s.scenario}>
                    <td className={`font-semibold ${SCEN_STYLE[s.scenario]}`}>{titleCase(s.scenario)}</td>
                    <td className="num">{pct(s.projected_return, true)}</td>
                    <td className="num">{price(s.projected_price)}</td>
                    <td className="num text-muted">
                      {price(s.interval_low)}–{price(s.interval_high)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <FanChart f={f} />
            {drivers.length ? (
              <div>
                <h4 className="mb-1 text-xs font-semibold text-muted">What moves the base case</h4>
                <ul className="grid grid-cols-2 gap-x-3 text-xs">
                  {drivers.map(([k, v]) => (
                    <li key={k} className="flex justify-between gap-2 border-b border-line py-0.5">
                      <span className="truncate">{titleCase(k)}</span>
                      <span className={`tabular-nums ${v > 0 ? 'text-opt' : v < 0 ? 'text-pes' : 'text-muted'}`}>{pct(v, true)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {applied.length ? (
              <p className="text-[11px] text-muted">
                <span className="font-semibold">Assumptions applied:</span> {applied.join('; ')}.
              </p>
            ) : null}
          </>
        ) : null}
        <p className="text-[11px] text-muted">
          Price return from {price(f.start_price)}
          {f.start_date ? ` on ${day(f.start_date)}` : ''}. Method {f.method}, {f.sample_size} days of history. Probabilities are not calibrated.
        </p>
      </div>
    </article>
  )
}

function ScenarioPanel({ securityId }: { securityId: string }) {
  const { asOf } = useApp()
  const settings = useSettings()
  const [assumptions, setAssumptions] = useState<ScenarioAssumptions | null>(null)
  useEffect(() => {
    if (!assumptions && settings.data) setAssumptions(settings.data.assumptions)
  }, [settings.data, assumptions])
  const a = assumptions ?? settings.data?.assumptions ?? null
  const req: ForecastRequest | null = a
    ? { security_ids: [securityId], horizons: ['short', 'medium', 'long'], assumptions: a, as_of: asOf ? asOfDateToIso(asOf) : null }
    : null
  const q = useForecast(req)
  const run = q.data
  const order: Horizon[] = ['short', 'medium', 'long']
  const fcs = order.map((h) => run?.forecasts.find((f) => f.horizon === h && f.security_id === securityId)).filter(Boolean) as SecurityForecast[]
  return (
    <Panel
      id="scenarios"
      title="Scenario forecasts"
      description="Optimistic, base and pessimistic cases with stated intervals. Not predictions of what will happen."
      aside={<ProvenanceButton runId={run?.run_id} />}
    >
      {a ? <AssumptionsEditor value={a} onChange={setAssumptions} pending={q.isFetching} /> : <Loading label="Loading default assumptions" />}
      <div className="mt-4">
        <ErrorBox error={q.error} />
        {q.isLoading ? <Loading label="Computing scenarios" /> : null}
        {run ? (
          <p className="mb-2 text-xs text-muted">
            As of {dateTime(run.as_of)} · data cutoff {dateTime(run.data_cutoff)} · model {run.model_version}
          </p>
        ) : null}
        <div className={`grid gap-3 xl:grid-cols-3 ${q.isFetching ? 'opacity-70' : ''}`}>
          {fcs.map((f) => (
            <HorizonCard key={f.horizon} f={f} />
          ))}
        </div>
      </div>
    </Panel>
  )
}

// ------------------------------------------------------------------ page

export default function Research() {
  const { securityId = 'JPM' } = useParams()
  const { asOf } = useApp()
  const secs = useSecurities()
  const sec = secs.data?.find((s) => s.security_id === securityId)
  const anchor = useAnchorDate(asOf)
  const prices = usePrices(securityId, asOf, yearsBefore(anchor, 3))
  const pts = prices.data?.points ?? []
  const last = pts[pts.length - 1]
  const prev = pts[pts.length - 2]
  const chg = last && prev ? last.close / prev.close - 1 : null
  const unknown = secs.data && !sec

  if (unknown) {
    return (
      <div className="panel p-6">
        <h1 className="text-lg font-semibold">Unknown security “{securityId}”</h1>
        <p className="text-sm text-muted">Pick one of the five banks from the Security menu above.</p>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-[1400px] space-y-4">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-2 pt-1">
        <div className="min-w-0">
          <p className="text-xs text-muted">
            {sec?.role === 'focal' ? 'Focal company' : 'Peer'} · {sec?.ticker ?? securityId}
          </p>
          <h1 className="serif text-[28px] leading-tight font-semibold sm:text-[34px]">{sec?.name ?? securityId}</h1>
        </div>
        {last ? (
          <div className="flex items-baseline gap-3 pb-1">
            <span className="text-2xl font-semibold tabular-nums">{price(last.close)}</span>
            <span className={`text-sm font-semibold tabular-nums ${chg != null && chg >= 0 ? 'text-opt' : 'text-pes'}`}>{pct(chg, true)}</span>
            <span className="text-xs text-muted">close {day(last.date)}</span>
            <OriginBadge origin={prices.data?.origin} />
          </div>
        ) : null}
      </div>

      <PricePanel securityId={securityId} anchor={anchor} />
      <ScenarioPanel securityId={securityId} />
      <div className="grid gap-4 xl:grid-cols-2">
        <PeerPanel securityId={securityId} anchor={anchor} />
        <AnalystPanel securityId={securityId} lastPrice={last?.close ?? null} />
      </div>
      <FundamentalsPanel securityId={securityId} anchor={anchor} />
    </div>
  )
}
