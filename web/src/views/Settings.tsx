import { useEffect, useId, useState } from 'react'
import { useLocation } from 'react-router'
import { useSaveSettings, useSettings, useSources } from '../api/hooks'
import { ApiError } from '../api/client'
import type { AlertRule, Horizon, Settings as SettingsT, SourceHealth } from '../api/types'
import { dateTime, day, titleCase } from '../lib/format'
import { ErrorBox, FieldError, Label, Loading, Panel } from '../components/ui'

const HEALTH_STYLE: Record<SourceHealth, string> = {
  fresh: 'text-ok',
  stale: 'text-warn',
  missing: 'text-danger',
  error: 'text-danger',
  disabled: 'text-muted',
}

const PCT_RULE_METRICS = new Set(['forecast_drawdown', 'downside_probability', 'realized_loss', 'concentration', 'event_severity'])

function numberOr(v: string, fallback: number): number {
  const n = Number(v)
  return v.trim() === '' || !Number.isFinite(n) ? fallback : n
}

export function SourcesTable() {
  const q = useSources()
  return (
    <Panel id="sources" title="Sources and freshness" description="Where the data comes from and how current it is.">
      {q.isLoading ? <Loading /> : null}
      <ErrorBox error={q.error} />
      {q.data ? (
        <div className="scroll-x">
          <table className="data text-xs">
            <thead>
              <tr>
                <th>Source</th>
                <th>State</th>
                <th>Latest record</th>
                <th>Last fetched</th>
                <th className="num">Records</th>
                <th>Note</th>
              </tr>
            </thead>
            <tbody>
              {q.data.map((s) => (
                <tr key={s.source_id}>
                  <td>
                    <div className="font-semibold">{s.name}</div>
                    <div className="text-muted">{s.source_id}</div>
                  </td>
                  <td className={`font-semibold ${HEALTH_STYLE[s.health]}`}>{titleCase(s.health)}</td>
                  <td>{day(s.latest_record_date)}</td>
                  <td>{dateTime(s.last_fetched_at)}</td>
                  <td className="num">{(s.record_count ?? 0).toLocaleString('en-US')}</td>
                  <td className="min-w-[14rem] text-ink-2">{s.message ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </Panel>
  )
}

export default function Settings() {
  const q = useSettings()
  const save = useSaveSettings()
  const base = useId()
  const loc = useLocation()
  const [draft, setDraft] = useState<SettingsT | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (q.data && !draft) setDraft(structuredClone(q.data))
  }, [q.data, draft])

  useEffect(() => {
    if (loc.hash === '#sources') document.getElementById('sources-title')?.scrollIntoView?.()
  }, [loc.hash, draft])

  if (q.isLoading || !draft) return <Loading label="Loading settings" />
  const fieldErr = save.error instanceof ApiError ? save.error.detail : null
  const errFor = (f: string) => (fieldErr?.field === f ? fieldErr.message : null)

  const set = (fn: (d: SettingsT) => void) => {
    const n = structuredClone(draft)
    fn(n)
    setDraft(n)
    setSaved(false)
  }
  const setRule = (i: number, patch: Partial<AlertRule>) => set((d) => { d.alert_rules[i] = { ...d.alert_rules[i], ...patch } })

  const hzErrors = (['short', 'medium', 'long'] as Horizon[]).map((h) => {
    const n = draft.horizon_days[h]
    return !Number.isInteger(n) || n < 1 || n > 1260 ? 'Whole number from 1 to 1260.' : null
  })
  const order = hzErrors.every((e) => !e) && !(draft.horizon_days.short < draft.horizon_days.medium && draft.horizon_days.medium < draft.horizon_days.long)
  const invalid = hzErrors.some(Boolean) || order

  return (
    <div className="mx-auto max-w-[1100px] space-y-4">
      <div className="pt-1">
        <h1 className="serif text-[28px] leading-tight font-semibold">Settings</h1>
        <p className="text-sm text-muted">Defaults for horizons, limits, alert rules and scenario assumptions. Runs record the settings hash they used.</p>
      </div>

      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (invalid) return
          save.mutate(draft, { onSuccess: (s) => { setDraft(structuredClone(s)); setSaved(true) } })
        }}
      >
        <Panel id="horizons" title="Horizons" description="Length of each forecast horizon, in market days.">
          <div className="grid grid-cols-3 gap-3 sm:max-w-md">
            {(['short', 'medium', 'long'] as Horizon[]).map((h, i) => {
              const id = `${base}-hz-${h}`
              const err = hzErrors[i] ?? errFor(`horizon_days.${h}`)
              return (
                <div key={h}>
                  <Label htmlFor={id}>{titleCase(h)}</Label>
                  <input
                    id={id}
                    type="number"
                    min={1}
                    max={1260}
                    step={1}
                    className="field w-full"
                    value={draft.horizon_days[h] ?? ''}
                    aria-invalid={!!err}
                    aria-describedby={`${id}-err`}
                    onChange={(e) => set((d) => { d.horizon_days[h] = Number(e.target.value) })}
                  />
                  <FieldError id={`${id}-err`}>{err}</FieldError>
                </div>
              )
            })}
          </div>
          {order ? <p className="mt-2 text-xs font-semibold text-danger">Short must be shorter than medium, and medium shorter than long.</p> : null}
        </Panel>

        <Panel id="limits" title="Default limits" description="Used when a portfolio does not set its own.">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {(
              [
                ['max_position_weight', 'Max per position', '%'],
                ['min_cash_weight', 'Min cash', '%'],
                ['max_cash_weight', 'Max cash', '%'],
                ['cash_annual_yield', 'Cash yield', '% a year'],
              ] as const
            ).map(([k, label, hint]) => (
              <div key={k}>
                <Label htmlFor={`${base}-${k}`} hint={hint}>
                  {label}
                </Label>
                <input
                  id={`${base}-${k}`}
                  type="number"
                  step="any"
                  min={0}
                  className="field w-full"
                  value={Math.round((draft.constraints[k] ?? 0) * 10000) / 100}
                  onChange={(e) => set((d) => { d.constraints[k] = numberOr(e.target.value, 0) / 100 })}
                />
              </div>
            ))}
            <div>
              <Label htmlFor={`${base}-cost`} hint="bps">
                Cost per change
              </Label>
              <input id={`${base}-cost`} type="number" min={0} step="any" className="field w-full" value={draft.constraints.transaction_cost_bps ?? 0} onChange={(e) => set((d) => { d.constraints.transaction_cost_bps = numberOr(e.target.value, 0) })} />
            </div>
            <div>
              <Label htmlFor={`${base}-ra`}>Risk aversion</Label>
              <input id={`${base}-ra`} type="number" min={0} step="any" className="field w-full" value={draft.constraints.risk_aversion ?? 3} onChange={(e) => set((d) => { d.constraints.risk_aversion = numberOr(e.target.value, 0) })} />
            </div>
          </div>
        </Panel>

        <Panel id="rules" title="Alert rules" description="When a rule's metric goes above its threshold, an alert is raised for your review.">
          <div className="scroll-x">
            <table className="data text-xs">
              <thead>
                <tr>
                  <th>On</th>
                  <th>Rule</th>
                  <th className="num">Threshold</th>
                  <th>Severity</th>
                  <th className="num">Cooldown</th>
                </tr>
              </thead>
              <tbody>
                {draft.alert_rules.map((r, i) => {
                  const id = `${base}-r-${r.rule_id}`
                  const pctRule = PCT_RULE_METRICS.has(r.metric)
                  return (
                    <tr key={r.rule_id}>
                      <td>
                        <input id={`${id}-on`} type="checkbox" checked={r.enabled !== false} onChange={(e) => setRule(i, { enabled: e.target.checked })} aria-label={`Enable ${r.rule_id}`} />
                      </td>
                      <td className="min-w-[16rem]">
                        <label htmlFor={`${id}-on`} className="font-semibold">
                          {r.rule_id} <span className="font-normal text-muted">v{r.version ?? 1}</span>
                        </label>
                        <div className="text-ink-2">{r.description}</div>
                        <div className="text-[11px] text-muted">
                          {titleCase(r.metric)} · {titleCase(r.horizon ?? 'short')} horizon
                          {r.loss_level != null ? ` · loss level ${Math.round(r.loss_level * 100)}%` : ''}
                          {r.lookback_trading_days != null ? ` · ${r.lookback_trading_days}-day lookback` : ''}
                        </div>
                      </td>
                      <td className="num">
                        <label className="sr-only" htmlFor={`${id}-th`}>
                          Threshold for {r.rule_id}
                        </label>
                        <span className="inline-flex items-center gap-1">
                          <input
                            id={`${id}-th`}
                            type="number"
                            step="any"
                            min={0}
                            className="field w-20 text-right"
                            value={pctRule ? Math.round(r.threshold * 10000) / 100 : r.threshold}
                            onChange={(e) => setRule(i, { threshold: pctRule ? numberOr(e.target.value, 0) / 100 : numberOr(e.target.value, 0) })}
                          />
                          {pctRule ? '%' : ''}
                        </span>
                      </td>
                      <td>
                        <label className="sr-only" htmlFor={`${id}-sev`}>
                          Severity for {r.rule_id}
                        </label>
                        <select id={`${id}-sev`} className="field" value={r.severity ?? 'warning'} onChange={(e) => setRule(i, { severity: e.target.value as AlertRule['severity'] })}>
                          {['info', 'warning', 'high', 'critical'].map((s) => (
                            <option key={s} value={s}>
                              {s}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="num">
                        <label className="sr-only" htmlFor={`${id}-cd`}>
                          Cooldown in market days for {r.rule_id}
                        </label>
                        <span className="inline-flex items-center gap-1">
                          <input id={`${id}-cd`} type="number" min={0} step={1} className="field w-16 text-right" value={r.cooldown_trading_days ?? 5} onChange={(e) => setRule(i, { cooldown_trading_days: Math.max(0, Math.round(numberOr(e.target.value, 0))) })} />
                          days
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel id="assume" title="Default scenario assumptions" description="Starting values for the assumptions editor on Stock research. Zero means history only.">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {(
              [
                ['rate_change_bps', 'Fed funds change', 'bps', 0],
                ['earnings_surprise_pct', 'Earnings surprise', '%', 0],
                ['market_return_shift_pct', 'Market return shift', '% a year', 0],
                ['volatility_multiplier', 'Volatility multiplier', 'x', 1],
                ['analyst_weight', 'Weight on analyst targets', '0 to 1', 0.25],
                ['lookback_years', 'History used', 'years', 5],
              ] as const
            ).map(([k, label, hint, dflt]) => (
              <div key={k}>
                <Label htmlFor={`${base}-a-${k}`} hint={hint}>
                  {label}
                </Label>
                <input
                  id={`${base}-a-${k}`}
                  type="number"
                  step="any"
                  className="field w-full"
                  value={draft.assumptions[k] ?? dflt}
                  onChange={(e) => set((d) => { d.assumptions[k] = numberOr(e.target.value, dflt) })}
                />
              </div>
            ))}
          </div>
        </Panel>

        <div className="panel sticky bottom-2 z-10 flex flex-wrap items-center gap-3 px-4 py-3">
          <button type="submit" className="btn btn-primary" disabled={save.isPending || invalid}>
            {save.isPending ? 'Saving…' : 'Save settings'}
          </button>
          <button type="button" className="btn" onClick={() => { setDraft(structuredClone(q.data!)); setSaved(false); save.reset() }}>
            Discard changes
          </button>
          <span role="status" className="text-xs font-semibold text-ok">
            {saved ? 'Settings saved.' : ''}
          </span>
          {save.error && !fieldErr?.field ? <ErrorBox error={save.error} /> : null}
          {fieldErr?.field && !fieldErr.field.startsWith('horizon_days') ? <span className="text-xs font-semibold text-danger">{fieldErr.message}</span> : null}
        </div>
      </form>

      <SourcesTable />
    </div>
  )
}
