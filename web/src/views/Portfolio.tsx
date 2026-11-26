import { useEffect, useId, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useEvaluatePortfolio, useOptimizePortfolio, useSecurities, useSettings } from '../api/hooks'
import { ApiError } from '../api/client'
import { DEFAULT_CONSTRAINTS, NEUTRAL_ASSUMPTIONS } from '../api/defaults'
import type { Allocation, Constraints, FeasibilityIssue, Horizon, Portfolio as PortfolioT, PortfolioEvaluation, PortfolioRequest } from '../api/types'
import { asOfDateToIso } from '../lib/asof'
import { dateTime, money, num, pct, titleCase } from '../lib/format'
import { useApp } from '../state/app'
import Heatmap from '../components/charts/Heatmap'
import { ErrorBox, FieldError, Label, Loading, OptionsNotice, Panel, ProvenanceButton, SimulatedTag, Stat } from '../components/ui'

interface Row {
  key: number
  security_id: string
  weight: string // percent
}

type ConstraintKey = 'max_position_weight' | 'min_cash_weight' | 'max_cash_weight' | 'max_turnover' | 'risk_aversion' | 'cash_annual_yield' | 'transaction_cost_bps'

const CONSTRAINT_FIELDS: Array<{ key: ConstraintKey; label: string; hint: string; percent: boolean; optional?: boolean }> = [
  { key: 'max_position_weight', label: 'Max per position', hint: '%', percent: true },
  { key: 'min_cash_weight', label: 'Min cash', hint: '%', percent: true },
  { key: 'max_cash_weight', label: 'Max cash', hint: '%', percent: true },
  { key: 'max_turnover', label: 'Max turnover', hint: '% (blank = none)', percent: true, optional: true },
  { key: 'risk_aversion', label: 'Risk aversion', hint: '0 or more', percent: false },
  { key: 'cash_annual_yield', label: 'Cash yield', hint: '% a year', percent: true },
  { key: 'transaction_cost_bps', label: 'Cost per change', hint: 'bps', percent: false },
]

let rowKey = 0
const toRows = (p: PortfolioT): Row[] => p.holdings.map((h) => ({ key: ++rowKey, security_id: h.security_id, weight: String(Math.round(h.weight * 10000) / 100) }))

function constraintDraft(c: Constraints): Record<ConstraintKey, string> {
  return Object.fromEntries(
    CONSTRAINT_FIELDS.map((f) => {
      const v = c[f.key]
      if (v === null || v === undefined) return [f.key, '']
      return [f.key, String(f.percent ? Math.round(Number(v) * 10000) / 100 : v)]
    }),
  ) as Record<ConstraintKey, string>
}

function issueFor(issues: FeasibilityIssue[], field: string): string | null {
  const hit = issues.filter((i) => i.field === field || i.field === `portfolio.${field}`)
  return hit.length ? hit.map((i) => i.message).join(' ') : null
}

function MetricsBlock({ a, value }: { a: Allocation; value: number }) {
  const m = a.metrics
  const p5 = m.prob_loss_exceeds?.['0.05']
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Expected return" value={pct(m.expected_return, true)} hint={`over ${m.horizon_trading_days} market days`} />
        <Stat label="Volatility" value={pct(m.volatility)} hint="std. dev. over horizon" />
        <Stat label="CVaR 95" value={pct(m.cvar_95)} hint={`avg loss, worst 5% · ${money(m.cvar_95 * value)}`} tone="bad" />
        <Stat label="Max drawdown (est.)" value={pct(m.max_drawdown_est)} hint="median simulated" />
        <Stat label="P(loss > 5%)" value={pct(p5)} hint={<SimulatedTag />} />
        <Stat label="Concentration (HHI)" value={num(m.concentration_hhi, 3)} hint={m.largest_position ? `largest ${m.largest_position} ${pct(m.largest_weight)}` : undefined} />
      </div>
      {a.scenario_pnl?.length ? (
        <div>
          <h3 className="mb-1 text-xs font-semibold text-muted">Scenario P&amp;L</h3>
          <div className="grid grid-cols-3 gap-2">
            {a.scenario_pnl.map((s) => (
              <div key={s.scenario} className={`rounded px-3 py-2 ${s.scenario === 'pessimistic' ? 'bg-pes-soft' : s.scenario === 'optimistic' ? 'bg-opt-soft' : 'inset'}`}>
                <div className="text-xs text-muted">{titleCase(s.scenario)}</div>
                <div className={`text-base font-semibold tabular-nums ${s.pnl >= 0 ? 'text-opt' : 'text-pes'}`}>{money(s.pnl)}</div>
                <div className="text-xs tabular-nums">{pct(s.return_pct, true)}</div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}

function Candidates({ ev, ids }: { ev: PortfolioEvaluation; ids: string[] }) {
  const all = [...(ev.current ? [ev.current] : []), ...(ev.candidates ?? []).filter((c) => c.label !== 'current')]
  const chart = all.map((a) => ({ label: a.label, 'Expected return': a.metrics.expected_return * 100, 'CVaR 95': a.metrics.cvar_95 * 100 }))
  return (
    <Panel
      id="cands"
      title="Candidate allocations"
      description="How other mixes would compare under the same assumptions."
      aside={<ProvenanceButton runId={ev.run_id} />}
    >
      <OptionsNotice className="mb-3" />
      <div className="scroll-x">
        <table className="data text-xs">
          <thead>
            <tr>
              <th>Allocation</th>
              {ids.map((id) => (
                <th key={id} className="num">
                  {id}
                </th>
              ))}
              <th className="num">Exp. return</th>
              <th className="num">Volatility</th>
              <th className="num">CVaR 95</th>
              <th className="num">P(loss&gt;5%)</th>
              <th className="num">Turnover</th>
              <th className="num">Est. cost</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>
            {all.map((a, i) => (
              <tr key={`${a.label}-${i}`} className={i === 0 ? 'bg-surface-2' : ''}>
                <td className="font-semibold whitespace-nowrap">{titleCase(a.label)}</td>
                {ids.map((id) => (
                  <td key={id} className="num">
                    {pct(a.weights[id] ?? 0)}
                  </td>
                ))}
                <td className="num">{pct(a.metrics.expected_return, true)}</td>
                <td className="num">{pct(a.metrics.volatility)}</td>
                <td className="num">{pct(a.metrics.cvar_95)}</td>
                <td className="num">{pct(a.metrics.prob_loss_exceeds?.['0.05'])}</td>
                <td className="num">{pct(a.turnover)}</td>
                <td className="num">{money(a.est_cost)}</td>
                <td className="min-w-[14rem] text-ink-2">{a.notes?.join(' ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-[11px] text-muted">P(loss&gt;5%) is simulated, uncalibrated.</p>
      <div className="mt-4 h-56" role="img" aria-label="Expected return and CVaR 95 by allocation, in percent">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chart} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--line)" />
            <XAxis dataKey="label" tickLine={false} axisLine={{ stroke: 'var(--line)' }} tickFormatter={(s: string) => titleCase(s)} />
            <YAxis width={36} tickLine={false} axisLine={false} tickFormatter={(v: number) => `${v}%`} />
            <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 4, fontSize: 12 }} formatter={(v, n) => [`${num(Number(v), 1)}%`, String(n)]} cursor={{ fill: 'var(--surface-2)' }} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="Expected return" fill="var(--opt)" isAnimationActive={false} />
            <Bar dataKey="CVaR 95" fill="var(--pes)" isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Panel>
  )
}

export default function Portfolio() {
  const { asOf } = useApp()
  const settings = useSettings()
  const secs = useSecurities()
  const evaluate = useEvaluatePortfolio()
  const optimize = useOptimizePortfolio()
  const base = useId()

  const [name, setName] = useState('My portfolio')
  const [total, setTotal] = useState('100000')
  const [horizon, setHorizon] = useState<Horizon>('medium')
  const [rows, setRows] = useState<Row[]>([])
  const [cons, setCons] = useState<Record<ConstraintKey, string> | null>(null)
  const [result, setResult] = useState<PortfolioEvaluation | null>(null)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    const p = settings.data?.default_portfolio
    if (p && rows.length === 0 && !cons) {
      setName(p.name ?? 'My portfolio')
      setTotal(String(p.total_value))
      setHorizon(p.horizon ?? 'medium')
      setRows(toRows(p))
      setCons(constraintDraft({ ...settings.data!.constraints, ...(p.constraints ?? {}) }))
    }
  }, [settings.data, rows.length, cons])

  const investable = (secs.data ?? []).filter((s) => s.investable)
  const sum = rows.reduce((a, r) => a + (Number(r.weight) || 0), 0)
  const sumOff = rows.length > 0 && Math.abs(sum - 100) > 0.01
  const totalNum = Number(total)
  const totalErr = !(totalNum > 0) ? 'Enter a value above 0.' : null

  const serverIssues: FeasibilityIssue[] = useMemo(() => {
    if (result && !result.feasible) return result.issues ?? []
    const err = (evaluate.error ?? optimize.error) as unknown
    if (err instanceof ApiError && err.detail) return [{ code: err.detail.code, message: err.detail.message, field: err.detail.field }]
    return []
  }, [result, evaluate.error, optimize.error])

  const change = <T,>(fn: (v: T) => void) => (v: T) => {
    fn(v)
    setDirty(true)
  }

  function buildRequest(): PortfolioRequest | null {
    if (!cons) return null
    const fields: Record<string, unknown> = { ...(settings.data?.constraints ?? DEFAULT_CONSTRAINTS) }
    for (const f of CONSTRAINT_FIELDS) {
      const raw = cons[f.key].trim()
      if (raw === '' && f.optional) fields[f.key] = null
      else fields[f.key] = f.percent ? Number(raw) / 100 : Number(raw)
    }
    const c = { ...fields, long_only: true, allow_leverage: false } as Constraints
    return {
      as_of: asOf ? asOfDateToIso(asOf) : null,
      portfolio: {
        portfolio_id: settings.data?.default_portfolio.portfolio_id ?? 'default',
        name,
        base_currency: 'USD',
        total_value: totalNum,
        horizon,
        holdings: rows.map((r) => ({ security_id: r.security_id, weight: (Number(r.weight) || 0) / 100 })),
        constraints: c,
      },
      assumptions: settings.data?.assumptions ?? NEUTRAL_ASSUMPTIONS,
    }
  }

  function run(kind: 'evaluate' | 'optimize') {
    const req = buildRequest()
    if (!req) return
    const m = kind === 'evaluate' ? evaluate : optimize
    ;(kind === 'evaluate' ? optimize : evaluate).reset()
    m.mutate(req, {
      onSuccess: (r) => {
        setResult(r)
        setDirty(false)
      },
      onError: () => setResult(null),
    })
  }

  if (settings.isLoading || !cons) return <Loading label="Loading your default portfolio" />

  const pending = evaluate.isPending || optimize.isPending
  const ids = [...new Set([...rows.map((r) => r.security_id), ...(result?.candidates?.flatMap((c) => Object.keys(c.weights)) ?? [])])].filter(Boolean)
  const generalIssues = serverIssues.filter((i) => {
    const f = i.field ?? ''
    return !(f === 'holdings' || /^(portfolio\.)?holdings\.\d+\./.test(f) || /^(portfolio\.)?constraints\./.test(f) || /total_value$/.test(f))
  })
  const sumIssue = issueFor(serverIssues, 'holdings')

  return (
    <div className="mx-auto max-w-[1400px] space-y-4">
      <div className="pt-1">
        <h1 className="serif text-[28px] leading-tight font-semibold">Portfolio</h1>
        <p className="text-sm text-muted">Enter holdings and limits, check the risk, then compare other mixes. Long-only, no leverage, USD.</p>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <Panel id="holdings" title="Holdings">
          <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <Label htmlFor={`${base}-name`}>Name</Label>
              <input id={`${base}-name`} className="field w-full" value={name} onChange={(e) => change(setName)(e.target.value)} />
            </div>
            <div>
              <Label htmlFor={`${base}-total`} hint="USD">
                Total value
              </Label>
              <input
                id={`${base}-total`}
                type="number"
                min={1}
                step={1000}
                className="field w-full"
                value={total}
                aria-invalid={!!(totalErr || issueFor(serverIssues, 'total_value'))}
                aria-describedby={`${base}-total-err`}
                onChange={(e) => change(setTotal)(e.target.value)}
              />
              <FieldError id={`${base}-total-err`}>{totalErr ?? issueFor(serverIssues, 'total_value')}</FieldError>
            </div>
            <div>
              <Label htmlFor={`${base}-hz`}>Horizon</Label>
              <select id={`${base}-hz`} className="field w-full" value={horizon} onChange={(e) => change(setHorizon)(e.target.value as Horizon)}>
                {(['short', 'medium', 'long'] as Horizon[]).map((h) => (
                  <option key={h} value={h}>
                    {titleCase(h)} ({settings.data?.horizon_days[h]} days)
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="scroll-x">
          <table className="data">
            <thead>
              <tr>
                <th>Security</th>
                <th className="num">Weight %</th>
                <th className="num hidden sm:table-cell">Value</th>
                <th>
                  <span className="sr-only">Remove</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const wErr = issueFor(serverIssues, `holdings.${i}.weight`)
                const sErr = issueFor(serverIssues, `holdings.${i}.security_id`)
                const w = Number(r.weight)
                const localW = r.weight.trim() === '' || !Number.isFinite(w) ? 'Enter a number.' : w < 0 || w > 100 ? 'Use 0 to 100.' : null
                return (
                  <tr key={r.key}>
                    <td>
                      <label className="sr-only" htmlFor={`${base}-s${r.key}`}>
                        Security, row {i + 1}
                      </label>
                      <select
                        id={`${base}-s${r.key}`}
                        className="field w-full min-w-[5.5rem]"
                        value={r.security_id}
                        aria-invalid={!!sErr}
                        aria-describedby={`${base}-s${r.key}-err`}
                        onChange={(e) => change(setRows)(rows.map((x) => (x.key === r.key ? { ...x, security_id: e.target.value } : x)))}
                      >
                        {investable.map((s) => (
                          <option key={s.security_id} value={s.security_id}>
                            {s.ticker}
                          </option>
                        ))}
                      </select>
                      <FieldError id={`${base}-s${r.key}-err`}>{sErr}</FieldError>
                    </td>
                    <td className="num">
                      <label className="sr-only" htmlFor={`${base}-w${r.key}`}>
                        Weight percent for {r.security_id}
                      </label>
                      <input
                        id={`${base}-w${r.key}`}
                        type="number"
                        min={0}
                        max={100}
                        step={1}
                        inputMode="decimal"
                        className="field w-20 text-right"
                        value={r.weight}
                        aria-invalid={!!(wErr || localW)}
                        aria-describedby={`${base}-w${r.key}-err`}
                        onChange={(e) => change(setRows)(rows.map((x) => (x.key === r.key ? { ...x, weight: e.target.value } : x)))}
                      />
                      <FieldError id={`${base}-w${r.key}-err`}>{localW ?? wErr}</FieldError>
                    </td>
                    <td className="num hidden text-muted sm:table-cell">{totalNum > 0 && Number.isFinite(w) ? money((w / 100) * totalNum) : '—'}</td>
                    <td className="text-right">
                      <button type="button" className="btn btn-quiet text-xs" onClick={() => change(setRows)(rows.filter((x) => x.key !== r.key))} aria-label={`Remove ${r.security_id}`}>
                        Remove
                      </button>
                    </td>
                  </tr>
                )
              })}
              <tr>
                <td>
                  <button
                    type="button"
                    className="btn btn-quiet text-xs"
                    onClick={() => {
                      const used = new Set(rows.map((r) => r.security_id))
                      const next = investable.find((s) => !used.has(s.security_id))?.security_id ?? 'CASH'
                      change(setRows)([...rows, { key: ++rowKey, security_id: next, weight: '0' }])
                    }}
                  >
                    Add a holding
                  </button>
                </td>
                <td className="num">
                  <span className={`font-semibold ${sumOff ? 'text-danger' : 'text-ok'}`} aria-live="polite">
                    {num(sum, 1)}%
                  </span>
                </td>
                <td className="num hidden font-semibold sm:table-cell">{totalNum > 0 ? money(totalNum * (sum / 100)) : '—'}</td>
                <td />
              </tr>
            </tbody>
          </table>
          </div>
          {sumOff ? (
            <p role="alert" className="mt-2 rounded border border-danger bg-danger-soft px-3 py-2 text-sm">
              Weights add up to {num(sum, 1)}%. They must add up to 100%.
              {sum > 100 ? ` Remove ${num(sum - 100, 1)} points.` : ` Add ${num(100 - sum, 1)} points, for example to CASH.`}
            </p>
          ) : sumIssue ? (
            <p role="alert" className="mt-2 rounded border border-danger bg-danger-soft px-3 py-2 text-sm">
              {sumIssue}
            </p>
          ) : null}
        </Panel>

        <Panel id="constraints" title="Limits" description="The model rejects a mix that breaks these.">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-2 2xl:grid-cols-3">
            {CONSTRAINT_FIELDS.map((f) => {
              const id = `${base}-c-${f.key}`
              const err = issueFor(serverIssues, `constraints.${f.key}`)
              return (
                <div key={f.key} className="min-w-0">
                  <Label htmlFor={id} hint={f.hint}>
                    {f.label}
                  </Label>
                  <input
                    id={id}
                    type="number"
                    step="any"
                    min={0}
                    className="field w-full"
                    value={cons[f.key]}
                    aria-invalid={!!err}
                    aria-describedby={`${id}-err`}
                    onChange={(e) => change(setCons)({ ...cons, [f.key]: e.target.value })}
                  />
                  <FieldError id={`${id}-err`}>{err}</FieldError>
                </div>
              )
            })}
          </div>
          <p className="mt-3 text-xs text-muted">Long-only and no leverage are fixed for this version.</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <button type="button" className="btn btn-primary" disabled={pending || !!totalErr || rows.length === 0} onClick={() => run('evaluate')}>
              {evaluate.isPending ? 'Evaluating…' : 'Evaluate'}
            </button>
            <button type="button" className="btn" disabled={pending || !!totalErr || rows.length === 0} onClick={() => run('optimize')}>
              {optimize.isPending ? 'Finding candidates…' : 'Find candidates'}
            </button>
          </div>
          {generalIssues.length ? (
            <ul role="alert" className="mt-3 space-y-1 rounded border border-danger bg-danger-soft px-3 py-2 text-sm">
              {generalIssues.map((i, k) => (
                <li key={k}>{i.message}</li>
              ))}
            </ul>
          ) : null}
          {!(evaluate.error instanceof ApiError) ? <ErrorBox error={evaluate.error} /> : null}
          {!(optimize.error instanceof ApiError) ? <ErrorBox error={optimize.error} /> : null}
        </Panel>
      </div>

      {result && !result.feasible ? (
        <div role="alert" className="panel border-danger px-4 py-3 text-sm">
          <strong className="text-danger">This portfolio cannot be evaluated as entered.</strong> Fix the {result.issues?.length ?? 0} highlighted field
          {(result.issues?.length ?? 0) === 1 ? '' : 's'} and try again.
        </div>
      ) : null}

      {result?.feasible && result.current ? (
        <>
          <Panel
            id="metrics"
            title="Current portfolio"
            description={`As of ${dateTime(result.as_of)} · model ${result.model_version}${dirty ? ' · inputs changed since this result' : ''}`}
            aside={<ProvenanceButton runId={result.run_id} />}
          >
            {dirty ? <p className="mb-3 text-xs font-semibold text-warn">You changed the inputs. Evaluate again to refresh these numbers.</p> : null}
            <MetricsBlock a={result.current} value={totalNum} />
          </Panel>
          {result.candidates?.length ? <Candidates ev={result} ids={ids} /> : null}
          <Panel id="corr" title="Correlation of daily returns" description="Last 5 years. Higher means holdings tend to move together, which limits diversification.">
            <Heatmap matrix={result.correlation ?? {}} />
          </Panel>
        </>
      ) : null}
      {!result && !pending ? (
        <p className="panel px-4 py-6 text-center text-sm text-muted">Press Evaluate to see risk numbers, or Find candidates to compare other mixes.</p>
      ) : null}
    </div>
  )
}
