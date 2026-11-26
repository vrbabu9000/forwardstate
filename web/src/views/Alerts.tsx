import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import { CartesianGrid, Line, LineChart, ReferenceDot, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useAlertRules, useAlerts, useEvents, useReplay, useSecurities, useSettings, useTransitionAlert } from '../api/hooks'
import type { Alert, AlertStatus, Event, EventClass, ReplayResult } from '../api/types'
import { DASH, day, dateTime, money, pct, titleCase } from '../lib/format'
import { useApp } from '../state/app'
import { EventDetail } from './Research'
import { MARKER_VAR, eventDate, markerClass } from '../components/charts/eventStyle'
import {
  ConfidenceBadge,
  Dot,
  ErrorBox,
  Label,
  Loading,
  OptionsNotice,
  OriginBadge,
  Panel,
  ProvenanceButton,
  SeverityBadge,
  SimulatedTag,
} from '../components/ui'

const STATUSES: Array<AlertStatus | ''> = ['', 'new', 'acknowledged', 'resolved', 'superseded']

// ------------------------------------------------------------------ alert detail

export function AlertDetail({ alert }: { alert: Alert }) {
  const t = useTransitionAlert()
  const status = alert.status ?? 'new'
  const exposure = Object.entries(alert.current_exposure ?? {})
  const totalExp = exposure.reduce((a, [, v]) => a + v, 0)
  return (
    <article className="space-y-4" aria-labelledby={`al-${alert.alert_id}`}>
      <header className="space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityBadge value={alert.severity} />
          <span className="text-xs font-semibold text-ink-2">{titleCase(status)}</span>
          <ConfidenceBadge value={alert.confidence} />
          <span className="ml-auto text-xs text-muted">{alert.alert_id}</span>
        </div>
        <h2 id={`al-${alert.alert_id}`} className="text-base leading-snug font-semibold">
          {alert.title}
        </h2>
        <p className="max-w-[75ch] text-sm text-ink-2">{alert.summary}</p>
      </header>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-4">
        <div>
          <dt className="text-muted">As of</dt>
          <dd className="font-semibold">{dateTime(alert.as_of)}</dd>
        </div>
        <div>
          <dt className="text-muted">Horizon</dt>
          <dd className="font-semibold">
            {titleCase(alert.horizon)}, {alert.horizon_trading_days} market days
          </dd>
        </div>
        <div>
          <dt className="text-muted">Rule</dt>
          <dd className="font-semibold">
            {alert.rule_id} v{alert.rule_version}
          </dd>
        </div>
        <div>
          <dt className="text-muted">{alert.superseded_by ? 'Superseded by' : 'Expires'}</dt>
          <dd className="font-semibold">{alert.superseded_by ?? dateTime(alert.expires_at)}</dd>
        </div>
        <div>
          <dt className="text-muted">Metric vs threshold</dt>
          <dd className="font-semibold">
            {pct(alert.metric_value)} vs {pct(alert.threshold)}
          </dd>
        </div>
        <div>
          <dt className="text-muted">Projected loss</dt>
          <dd className="font-semibold text-pes">
            {alert.projected_loss != null ? `${money(alert.projected_loss)} (${pct(alert.projected_loss_pct)})` : 'Not available'}
          </dd>
        </div>
        <div>
          <dt className="text-muted">Probability</dt>
          <dd className="font-semibold">
            {alert.probability != null ? pct(alert.probability) : 'Not available'} <SimulatedTag />
          </dd>
        </div>
        <div>
          <dt className="text-muted">Affected</dt>
          <dd className="font-semibold">{alert.affected_security_ids?.join(', ') || DASH}</dd>
        </div>
      </dl>

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="btn"
          disabled={status !== 'new' || t.isPending}
          onClick={() => t.mutate({ alertId: alert.alert_id, to: 'acknowledged' })}
        >
          Acknowledge
        </button>
        <button
          type="button"
          className="btn"
          disabled={!(status === 'new' || status === 'acknowledged') || t.isPending}
          onClick={() => t.mutate({ alertId: alert.alert_id, to: 'resolved' })}
        >
          Resolve
        </button>
        <span className="text-xs text-muted">Records your review. Nothing else changes.</span>
        <span className="ml-auto">
          <ProvenanceButton runId={alert.run_id} />
        </span>
      </div>
      <ErrorBox error={t.error} />

      <section aria-labelledby={`alt-${alert.alert_id}`}>
        <h3 id={`alt-${alert.alert_id}`} className="mb-1 text-sm font-semibold">
          Alternatives compared
        </h3>
        <OptionsNotice className="mb-2" />
        {alert.alternatives?.length ? (
          <div className="scroll-x">
            <table className="data text-xs">
              <thead>
                <tr>
                  <th>Option</th>
                  <th className="num">Exp. return</th>
                  <th className="num">CVaR 95</th>
                  <th className="num">Projected loss</th>
                  <th className="num">Est. cost</th>
                  <th className="num">Missed upside</th>
                  <th>Note</th>
                </tr>
              </thead>
              <tbody>
                {alert.alternatives.map((o) => (
                  <tr key={o.label}>
                    <td className="font-semibold whitespace-nowrap">{o.label}</td>
                    <td className="num">{pct(o.expected_return, true)}</td>
                    <td className="num">{pct(o.cvar_95)}</td>
                    <td className="num text-pes">{money(o.projected_loss)}</td>
                    <td className="num">{money(o.est_cost)}</td>
                    <td className="num">{money(o.missed_upside)}</td>
                    <td className="min-w-[14rem] text-ink-2">{o.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-muted">No alternatives were computed for this alert.</p>
        )}
      </section>

      <div className="grid gap-4 md:grid-cols-2">
        <section>
          <h3 className="mb-1 text-sm font-semibold">Evidence</h3>
          <ul className="space-y-1.5">
            {(alert.evidence ?? []).map((e) => (
              <li key={`${e.kind}-${e.ref_id}`} className="flex items-start gap-2 text-xs">
                <span className="w-14 shrink-0 font-semibold text-muted">{e.kind}</span>
                <span className="min-w-0 flex-1">
                  {e.label}
                  {e.at ? <span className="block text-[11px] text-muted">{dateTime(e.at)}</span> : null}
                </span>
                <OriginBadge origin={e.origin} />
              </li>
            ))}
          </ul>
        </section>
        <section>
          <h3 className="mb-1 text-sm font-semibold">Current exposure</h3>
          <table className="data text-xs">
            <tbody>
              {exposure.map(([k, v]) => (
                <tr key={k}>
                  <td className="font-semibold">{k}</td>
                  <td className="num">{money(v)}</td>
                  <td className="num text-muted">{totalExp ? pct(v / totalExp) : DASH}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3 className="mt-3 mb-1 text-sm font-semibold">Limitations</h3>
          <ul className="list-disc space-y-0.5 pl-4 text-xs text-ink-2">
            {(alert.limitations ?? []).map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </section>
      </div>

      <p className="rounded border border-line-strong bg-surface-2 px-3 py-2 text-xs" data-boundary>
        <strong>Your decision. </strong>
        {alert.decision_boundary}
      </p>
    </article>
  )
}

// ------------------------------------------------------------------ inbox

function Inbox({ selectedId, onSelect }: { selectedId: string | null; onSelect: (id: string) => void }) {
  const [status, setStatus] = useState<AlertStatus | ''>('')
  const q = useAlerts(status)
  const sid = useId()
  return (
    <div className="flex min-h-0 flex-col">
      <div className="mb-2 flex items-center gap-2">
        <label htmlFor={sid} className="text-xs font-semibold text-muted">
          Status
        </label>
        <select id={sid} className="field" value={status} onChange={(e) => setStatus(e.target.value as AlertStatus | '')}>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s ? titleCase(s) : 'All'}
            </option>
          ))}
        </select>
        <span className="ml-auto text-xs text-muted">{q.data ? `${q.data.length} alerts` : ''}</span>
      </div>
      {q.isLoading ? <Loading label="Loading alerts" /> : null}
      <ErrorBox error={q.error} />
      {q.data?.length === 0 ? <p className="py-4 text-sm text-muted">No alerts with this status. Run a replay below to see how rules behave.</p> : null}
      <ul className="max-h-[34rem] overflow-y-auto rounded border border-line">
        {q.data?.map((a) => (
          <li key={a.alert_id} className="border-b border-line last:border-0">
            <button
              type="button"
              onClick={() => onSelect(a.alert_id)}
              aria-pressed={selectedId === a.alert_id}
              className={`block w-full px-3 py-2 text-left ${selectedId === a.alert_id ? 'bg-accent-soft' : 'hover:bg-surface-2'} ${a.status === 'resolved' || a.status === 'superseded' ? 'opacity-70' : ''}`}
            >
              <span className="flex items-center gap-2">
                <SeverityBadge value={a.severity} />
                <span className="text-[11px] font-semibold text-ink-2">{titleCase(a.status ?? 'new')}</span>
                <span className="ml-auto text-[11px] text-muted">{day(a.as_of)}</span>
              </span>
              <span className="mt-0.5 block text-xs leading-snug font-semibold">{a.title}</span>
              <span className="block text-[11px] text-muted">
                Confidence {a.confidence} · {a.rule_id}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

// ------------------------------------------------------------------ replay

function ReplayPanel({ onOpenAlert }: { onOpenAlert: (id: string) => void }) {
  const settings = useSettings()
  const rules = useAlertRules()
  const replay = useReplay()
  const base = useId()
  const [start, setStart] = useState('2025-03-03')
  const [end, setEnd] = useState('2025-05-30')
  const [step, setStep] = useState('1')
  const [ruleIds, setRuleIds] = useState<string[] | null>(null)
  const enabled = (rules.data ?? []).filter((r) => r.enabled !== false)
  const chosen = ruleIds ?? enabled.map((r) => r.rule_id)
  const stepN = Number(step)
  const err = start > end ? 'Start must be on or before end.' : !(stepN >= 1 && stepN <= 20 && Number.isInteger(stepN)) ? 'Step must be a whole number from 1 to 20.' : chosen.length === 0 ? 'Pick at least one rule.' : null

  const res: ReplayResult | undefined = replay.data
  const alertById = useMemo(() => new Map((res?.alerts ?? []).map((a) => [a.alert_id, a])), [res])
  const markers = (res?.frames ?? []).filter((f) => f.new_alert_ids?.length)

  return (
    <Panel
      id="replay"
      title="Replay"
      description="Step through history with your default portfolio and see which rules would have fired. Nothing is sent."
      aside={<ProvenanceButton runId={res?.run_id} />}
    >
      <form
        className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-[repeat(3,minmax(0,10rem))_1fr_auto] lg:items-end"
        onSubmit={(e) => {
          e.preventDefault()
          if (err || !settings.data) return
          replay.mutate({ portfolio: settings.data.default_portfolio, start, end, step_trading_days: stepN, rule_ids: chosen, assumptions: settings.data.assumptions })
        }}
      >
        <div>
          <Label htmlFor={`${base}-s`}>Start</Label>
          <input id={`${base}-s`} type="date" className="field w-full" value={start} onChange={(e) => setStart(e.target.value)} />
        </div>
        <div>
          <Label htmlFor={`${base}-e`}>End</Label>
          <input id={`${base}-e`} type="date" className="field w-full" value={end} onChange={(e) => setEnd(e.target.value)} />
        </div>
        <div>
          <Label htmlFor={`${base}-st`} hint="market days">
            Step
          </Label>
          <input id={`${base}-st`} type="number" min={1} max={20} className="field w-full" value={step} onChange={(e) => setStep(e.target.value)} />
        </div>
        <fieldset className="col-span-2 min-w-0 sm:col-span-4 lg:col-span-1">
          <legend className="mb-1 text-xs font-semibold text-ink-2">Rules</legend>
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {enabled.map((r) => (
              <label key={r.rule_id} className="inline-flex items-center gap-1.5 text-xs">
                <input
                  type="checkbox"
                  checked={chosen.includes(r.rule_id)}
                  onChange={(e) => setRuleIds(e.target.checked ? [...chosen, r.rule_id] : chosen.filter((x) => x !== r.rule_id))}
                />
                {r.rule_id}
              </label>
            ))}
          </div>
        </fieldset>
        <button type="submit" className="btn btn-primary col-span-2 justify-center sm:col-span-1" disabled={!!err || replay.isPending || !settings.data}>
          {replay.isPending ? 'Replaying…' : 'Run replay'}
        </button>
      </form>
      {err ? <p className="mt-2 text-xs font-semibold text-danger">{err}</p> : null}
      <div className="mt-3">
        <ErrorBox error={replay.error} />
      </div>
      {res ? (
        <div className="mt-3 space-y-2">
          <p className="text-xs text-muted">
            {res.frames.length} steps from {day(res.start)} to {day(res.end)} · {res.alerts.length} alerts raised · mode {res.mode} · model {res.model_version}
          </p>
          <div className="h-60" role="img" aria-label={`Portfolio value during replay with ${markers.length} alert markers`}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={res.frames}
                margin={{ top: 10, right: 12, bottom: 0, left: 0 }}
                style={{ cursor: markers.length ? 'pointer' : undefined }}
                onClick={(state) => {
                  // Clicking at or right next to an alert marker opens that alert.
                  const label = state?.activeLabel != null ? String(state.activeLabel) : null
                  if (!label) return
                  const i = res.frames.findIndex((f) => f.as_of === label)
                  const near = [i, i - 1, i + 1].map((k) => res.frames[k]).find((f) => f?.new_alert_ids?.length)
                  if (near) onOpenAlert(near.new_alert_ids![0])
                }}
              >
                <CartesianGrid vertical={false} stroke="var(--line)" />
                <XAxis dataKey="as_of" tickLine={false} axisLine={{ stroke: 'var(--line)' }} minTickGap={40} tickFormatter={(d: string) => d.slice(5)} />
                <YAxis width={64} tickLine={false} axisLine={false} domain={['auto', 'auto']} tickFormatter={(v: number) => `$${Math.round(v / 1000)}k`} />
                <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 4, fontSize: 12 }} labelFormatter={(d) => day(String(d))} formatter={(v) => [money(Number(v)), 'Value, no change']} />
                <Line dataKey="portfolio_value" stroke="var(--accent)" strokeWidth={2} dot={false} isAnimationActive={false} />
                {markers.map((f) => {
                  const a = alertById.get(f.new_alert_ids![0])
                  const sev = a?.severity ?? 'warning'
                  return (
                    <ReferenceDot
                      key={f.as_of}
                      x={f.as_of}
                      y={f.portfolio_value}
                      r={6}
                      fill={sev === 'info' ? 'var(--accent)' : sev === 'warning' ? 'var(--warn)' : 'var(--danger)'}
                      stroke="var(--surface)"
                      strokeWidth={2}
                      style={{ cursor: 'pointer' }}
                      onClick={() => onOpenAlert(f.new_alert_ids![0])}
                    />
                  )
                })}
              </LineChart>
            </ResponsiveContainer>
          </div>
          {markers.length ? (
            <div>
              <h3 className="mb-1 text-xs font-semibold text-muted">Alerts raised during the replay</h3>
              <ul className="flex flex-wrap gap-1.5">
                {markers.flatMap((f) =>
                  f.new_alert_ids!.map((id) => {
                    const a = alertById.get(id)
                    return (
                      <li key={id}>
                        <button type="button" className="btn text-xs" onClick={() => onOpenAlert(id)}>
                          {day(f.as_of)} · {a ? `${a.severity}: ${a.rule_id}` : id}
                        </button>
                      </li>
                    )
                  }),
                )}
              </ul>
            </div>
          ) : (
            <p className="text-sm text-muted">No rule fired in this window.</p>
          )}
        </div>
      ) : null}
    </Panel>
  )
}

// ------------------------------------------------------------------ timeline

function Timeline() {
  const { asOf } = useApp()
  const secs = useSecurities()
  const [cls, setCls] = useState<EventClass | ''>('')
  const [sec, setSec] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  const base = useId()
  const anchor = asOf ?? '2025-11-21'
  const start = `${Number(anchor.slice(0, 4)) - 1}${anchor.slice(4)}`
  const q = useEvents({ event_class: cls, security_id: sec || undefined, start }, asOf)
  const list = [...(q.data ?? [])].reverse()
  return (
    <Panel id="timeline" title="Event timeline" description="Last 12 months and anything upcoming. Impact numbers are associations, not causes.">
      <div className="mb-3 flex flex-wrap gap-3">
        <div>
          <Label htmlFor={`${base}-c`}>Class</Label>
          <select id={`${base}-c`} className="field" value={cls} onChange={(e) => setCls(e.target.value as EventClass | '')}>
            <option value="">All classes</option>
            <option value="scheduled">Scheduled</option>
            <option value="anticipated">Anticipated</option>
            <option value="unexpected">Unexpected</option>
          </select>
        </div>
        <div>
          <Label htmlFor={`${base}-sec`}>Security</Label>
          <select id={`${base}-sec`} className="field" value={sec} onChange={(e) => setSec(e.target.value)}>
            <option value="">All banks</option>
            {(secs.data ?? [])
              .filter((s) => s.role === 'focal' || s.role === 'peer')
              .map((s) => (
                <option key={s.security_id} value={s.security_id}>
                  {s.ticker}
                </option>
              ))}
          </select>
        </div>
        <p className="self-end text-xs text-muted">{q.data ? `${q.data.length} events` : ''}</p>
      </div>
      {q.isLoading ? <Loading label="Loading events" /> : null}
      <ErrorBox error={q.error} />
      <ol className="max-h-[40rem] overflow-y-auto rounded border border-line">
        {list.length === 0 && !q.isLoading ? <li className="px-3 py-3 text-sm text-muted">No events match these filters.</li> : null}
        {list.map((e: Event) => {
          const c = markerClass(e)
          const isOpen = open === e.event_id
          return (
            <li key={e.event_id} className="border-b border-line last:border-0">
              <button
                type="button"
                aria-expanded={isOpen}
                onClick={() => setOpen(isOpen ? null : e.event_id)}
                className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs ${isOpen ? 'bg-surface-2' : 'hover:bg-surface-2'}`}
              >
                <Dot color={`var(${MARKER_VAR[c]})`} />
                <span className="w-[5.5rem] shrink-0 text-muted tabular-nums">{day(eventDate(e))}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-semibold">{e.title}</span>
                  <span className="block text-[11px] text-muted">
                    {titleCase(e.event_class)} · {(e.affected_security_ids ?? []).join(', ')}
                    {e.canonical_event_id ? ' · repeat report' : ''}
                  </span>
                </span>
                {e.status === 'upcoming' ? <span className="text-[11px] font-semibold text-warn">upcoming</span> : null}
                <OriginBadge origin={e.origin} />
              </button>
              {isOpen ? (
                <div className="border-t border-line bg-surface-2 px-3 py-3">
                  <EventDetail event={e} />
                </div>
              ) : null}
            </li>
          )
        })}
      </ol>
    </Panel>
  )
}

// ------------------------------------------------------------------ page

export default function Alerts() {
  const [params, setParams] = useSearchParams()
  const selected = params.get('alert')
  const all = useAlerts('')
  const detailRef = useRef<HTMLDivElement>(null)
  const alert = all.data?.find((a) => a.alert_id === selected) ?? null

  useEffect(() => {
    if (!selected && all.data?.length) {
      const first = all.data.find((a) => a.status === 'new') ?? all.data[0]
      setParams((p) => { p.set('alert', first.alert_id); return p }, { replace: true })
    }
  }, [selected, all.data, setParams])

  const openAlert = (id: string) => {
    setParams((p) => { p.set('alert', id); return p })
    requestAnimationFrame(() => {
      detailRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
      detailRef.current?.focus()
    })
  }

  return (
    <div className="mx-auto max-w-[1400px] space-y-4">
      <div className="pt-1">
        <h1 className="serif text-[28px] leading-tight font-semibold">Events &amp; alerts</h1>
        <p className="text-sm text-muted">Alerts flag possible losses for your review. They never change your holdings.</p>
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <Panel id="inbox" title="Alert inbox">
          <Inbox selectedId={selected} onSelect={openAlert} />
        </Panel>
        <div ref={detailRef} tabIndex={-1} className="min-w-0 outline-none">
          <Panel id="detail" title="Alert detail">
            {all.isLoading ? <Loading /> : null}
            {alert ? <AlertDetail alert={alert} /> : !all.isLoading ? <p className="text-sm text-muted">Pick an alert from the inbox.</p> : null}
          </Panel>
        </div>
      </div>
      <ReplayPanel onOpenAlert={openAlert} />
      <Timeline />
    </div>
  )
}
