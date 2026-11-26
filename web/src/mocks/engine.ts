/**
 * Mock "backend" logic over the synthetic data. Simple, deterministic and honest:
 * normal-approximation risk numbers, no calibration. Shapes match contracts.schema.json.
 */
import type {
  ActionOption,
  Alert,
  AlertRule,
  AlertSeverity,
  Allocation,
  Constraints,
  EvidenceItem,
  FeasibilityIssue,
  ForecastRequest,
  ForecastRun,
  Horizon,
  ImpactEstimate,
  Portfolio,
  PortfolioEvaluation,
  PortfolioRequest,
  ReplayFrame,
  ReplayRequest,
  ReplayResult,
  ReproduceResult,
  RiskMetrics,
  RunKind,
  RunRecord,
  ScenarioAssumptions,
  ScenarioForecast,
  ScenarioPnL,
  SecurityForecast,
  Settings,
} from '../api/types'
import {
  ANALYSTS,
  BANKS,
  CLOSES,
  DAYS,
  DECISION_BOUNDARY,
  EVENTS,
  LATEST_ISO,
  MODEL_VERSION,
  RETURNS,
  SECURITIES,
  SOURCES,
  dayIndexAtOrBefore,
  dffAt,
  eventAsOf,
} from './data'

// ---------------------------------------------------------------- hashing

function stableStringify(v: unknown): string {
  if (v === null || typeof v !== 'object') return JSON.stringify(v ?? null)
  if (Array.isArray(v)) return `[${v.map(stableStringify).join(',')}]`
  const o = v as Record<string, unknown>
  return `{${Object.keys(o).sort().map((k) => `${JSON.stringify(k)}:${stableStringify(o[k])}`).join(',')}}`
}

/** Deterministic 64-hex hash (not sha256; mock only). */
export function mockHash(v: unknown): string {
  const s = stableStringify(v)
  let out = ''
  for (let seed = 1; seed <= 8; seed++) {
    let h = 0x811c9dc5 ^ (seed * 0x9e3779b1)
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i)
      h = Math.imul(h, 0x01000193)
    }
    out += (h >>> 0).toString(16).padStart(8, '0')
  }
  return out
}

// ---------------------------------------------------------------- as_of

/** Turn a query/body as_of (date or datetime) into an ISO instant, capped at the latest data. */
export function resolveAsOf(v: string | null | undefined): string {
  if (!v) return LATEST_ISO
  let t: string
  if (/^\d{4}-\d{2}-\d{2}$/.test(v)) t = new Date(`${v}T23:59:00-05:00`).toISOString()
  else t = new Date(v).toISOString()
  t = t.replace('.000', '')
  return t > LATEST_ISO ? LATEST_ISO : t
}

export function asOfIndex(asOfIso: string): number {
  // Prices close 21:00 UTC; a bar is knowable once its day is done.
  const d = new Date(asOfIso)
  const ny = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(d)
  return dayIndexAtOrBefore(ny)
}

// ---------------------------------------------------------------- settings & runs

export const DEFAULT_ASSUMPTIONS: Assume = {
  rate_change_bps: 0,
  earnings_surprise_pct: 0,
  market_return_shift_pct: 0,
  volatility_multiplier: 1,
  analyst_weight: 0.25,
  lookback_years: 5,
  notes: null,
}

type Cons = Required<Omit<Constraints, 'max_turnover'>> & { max_turnover: number | null }
type Assume = Required<Omit<ScenarioAssumptions, 'notes'>> & { notes: string | null }

const DEFAULT_CONSTRAINTS: Cons = {
  max_position_weight: 0.4,
  min_cash_weight: 0,
  max_cash_weight: 1,
  max_turnover: null,
  risk_aversion: 3,
  cash_annual_yield: 0.04,
  transaction_cost_bps: 5,
  long_only: true,
  allow_leverage: false,
}

const DEFAULT_RULES: AlertRule[] = [
  { rule_id: 'forecast_drawdown_short', version: 1, description: 'Simulated short-horizon loss in the worst 5% (CVaR) above threshold', metric: 'forecast_drawdown', horizon: 'short', threshold: 0.16, loss_level: null, lookback_trading_days: null, severity: 'high', cooldown_trading_days: 10, enabled: true },
  { rule_id: 'downside_probability_5pct', version: 1, description: 'Chance of losing more than 5% over the short horizon above threshold', metric: 'downside_probability', horizon: 'short', threshold: 0.25, loss_level: 0.05, lookback_trading_days: null, severity: 'warning', cooldown_trading_days: 10, enabled: true },
  { rule_id: 'realized_loss_10d', version: 1, description: 'Actual portfolio loss over the last 10 market days above threshold', metric: 'realized_loss', horizon: 'short', threshold: 0.06, loss_level: null, lookback_trading_days: 10, severity: 'high', cooldown_trading_days: 5, enabled: true },
  { rule_id: 'concentration', version: 1, description: 'Largest single position above threshold', metric: 'concentration', horizon: 'short', threshold: 0.45, loss_level: null, lookback_trading_days: null, severity: 'info', cooldown_trading_days: 20, enabled: true },
  { rule_id: 'event_severity', version: 1, description: 'An event moved a holding by more than the threshold (abnormal return)', metric: 'event_severity', horizon: 'short', threshold: 0.04, loss_level: null, lookback_trading_days: null, severity: 'warning', cooldown_trading_days: 3, enabled: false },
]

export const DEFAULT_PORTFOLIO: Portfolio = {
  portfolio_id: 'default',
  name: 'Bank sleeve (synthetic)',
  base_currency: 'USD',
  total_value: 100000,
  holdings: [
    { security_id: 'JPM', weight: 0.35 },
    { security_id: 'BAC', weight: 0.2 },
    { security_id: 'C', weight: 0.1 },
    { security_id: 'MS', weight: 0.15 },
    { security_id: 'GS', weight: 0.15 },
    { security_id: 'CASH', weight: 0.05 },
  ],
  horizon: 'medium',
  constraints: DEFAULT_CONSTRAINTS,
}

export function freshSettings(): Settings {
  return structuredClone({
    horizon_days: { short: 20, medium: 126, long: 504 },
    constraints: DEFAULT_CONSTRAINTS,
    assumptions: DEFAULT_ASSUMPTIONS,
    alert_rules: DEFAULT_RULES,
    default_portfolio: DEFAULT_PORTFOLIO,
  })
}

interface DB {
  settings: Settings
  runs: RunRecord[]
  outputs: Map<string, unknown>
  alerts: Alert[]
  seq: number
  clock: number
}

export const db: DB = { settings: freshSettings(), runs: [], outputs: new Map(), alerts: [], seq: 0, clock: Date.parse('2025-11-26T14:00:00Z') }

export function resetDb() {
  db.settings = freshSettings()
  db.runs = []
  db.outputs = new Map()
  db.alerts = []
  db.seq = 0
  db.clock = Date.parse('2025-11-26T14:00:00Z')
  seedAlerts()
}

function nowIso(): string {
  db.clock += 37_000
  return new Date(db.clock).toISOString().replace('.000', '')
}

function nextId(prefix: string): string {
  db.seq += 1
  return `${prefix}-${String(db.seq).padStart(5, '0')}`
}

const VOLATILE = new Set(['run_id', 'created_at', 'alert_id', 'new_alert_ids', 'alerts', 'superseded_by'])
function outputHash(output: unknown): string {
  const strip = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(strip)
    if (v && typeof v === 'object') {
      return Object.fromEntries(Object.entries(v as Record<string, unknown>).filter(([k]) => !VOLATILE.has(k)).map(([k, x]) => [k, strip(x)]))
    }
    return v
  }
  return mockHash(strip(output))
}

function record(kind: RunKind, runId: string, request: Record<string, unknown>, asOfIso: string, output: unknown): RunRecord {
  const rec: RunRecord = {
    run_id: runId,
    kind,
    created_at: nowIso(),
    as_of: asOfIso,
    data_cutoff: asOfIso,
    model_version: MODEL_VERSION,
    contract_version: '1.0.0',
    config_hash: mockHash(db.settings),
    input_hash: mockHash({ request, cutoff: asOfIso, sources: SOURCES.map((s) => [s.source_id, s.health]) }),
    output_hash: outputHash(output),
    request,
    data_origin: 'synthetic',
    source_status: SOURCES.map((s) => ({ source_id: s.source_id, health: s.health, latest_record_date: s.latest_record_date })),
  }
  db.runs.unshift(rec)
  db.outputs.set(runId, { kind, request })
  return rec
}

function consOf(c: Constraints | undefined): Cons {
  return { ...DEFAULT_CONSTRAINTS, ...(c ?? {}) } as Cons
}
function assumeOf(a: ScenarioAssumptions | undefined): Assume {
  return { ...DEFAULT_ASSUMPTIONS, ...(a ?? {}) } as Assume
}

// ---------------------------------------------------------------- statistics

const Z90 = 1.2815515655446004

function phi(x: number): number {
  return Math.exp(-0.5 * x * x) / Math.sqrt(2 * Math.PI)
}

/** Standard normal CDF (Abramowitz-Stegun). */
function Phi(x: number): number {
  const t = 1 / (1 + 0.2316419 * Math.abs(x))
  const d = 0.3989423 * Math.exp((-x * x) / 2)
  const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))))
  return x > 0 ? 1 - p : p
}

function stats(id: string, endIdx: number, lookbackDays: number) {
  const r = RETURNS[id]
  const start = Math.max(1, endIdx - lookbackDays + 1)
  const xs = r.slice(start, endIdx + 1)
  const n = xs.length
  const mu = xs.reduce((a, b) => a + b, 0) / Math.max(n, 1)
  const v = xs.reduce((a, b) => a + (b - mu) ** 2, 0) / Math.max(n - 1, 1)
  return { mu, sigma: Math.sqrt(v), n }
}

function covariance(ids: string[], endIdx: number, lookbackDays: number): number[][] {
  const start = Math.max(1, endIdx - lookbackDays + 1)
  const series = ids.map((id) => (id === 'CASH' ? null : RETURNS[id].slice(start, endIdx + 1)))
  const means = series.map((s) => (s ? s.reduce((a, b) => a + b, 0) / s.length : 0))
  return ids.map((_, i) =>
    ids.map((__, j) => {
      const a = series[i]
      const b = series[j]
      if (!a || !b) return 0
      let c = 0
      for (let k = 0; k < a.length; k++) c += (a[k] - means[i]) * (b[k] - means[j])
      return c / (a.length - 1)
    }),
  )
}

const RATE_SENS: Record<string, number> = { JPM: 0.012, BAC: 0.018, C: 0.014, MS: 0.006, GS: 0.005 }

// ---------------------------------------------------------------- forecast

function horizonDays(h: Horizon): number {
  return db.settings.horizon_days[h] ?? { short: 20, medium: 126, long: 504 }[h]
}

function latestTarget(id: string, asOfIso: string): number | null {
  const obs = ANALYSTS.filter((a) => a.security_id === id && a.available_at <= asOfIso && a.target_price != null)
  return obs.length ? (obs[obs.length - 1].target_price as number) : null
}

function forecastOne(id: string, h: Horizon, a: ScenarioAssumptions, idx: number, asOfIso: string): SecurityForecast {
  const H = horizonDays(h)
  const lookback = Math.round((a.lookback_years ?? 5) * 252)
  const base: SecurityForecast = {
    security_id: id, horizon: h, horizon_trading_days: H, return_type: 'price',
    start_price: idx >= 0 ? CLOSES[id]?.[idx] ?? null : null, start_date: idx >= 0 ? DAYS[idx] : null,
    scenarios: [], status: 'high', status_reason: null, method: 'mock_lognormal_history_plus_assumptions',
    model_version: MODEL_VERSION, feature_snapshot_id: idx >= 0 ? `fs-${id}-${DAYS[idx]}` : null, sample_size: 0, drivers: {},
  }
  if (!CLOSES[id] || idx < 0) {
    return { ...base, status: 'unavailable', status_reason: `No price history for ${id} as of this date.` }
  }
  const s = stats(id, idx, lookback)
  base.sample_size = s.n
  const needed = Math.min(lookback, H * 2)
  // Synthetic data-quality gaps so the UI shows both states honestly.
  if (id === 'C' && h === 'long') {
    return { ...base, status: 'unavailable', status_reason: 'Not enough clean history for a 2-year view: synthetic gap in C price history before 2021 (fixture). No number is shown rather than a guess.', sample_size: 0 }
  }
  if (s.n < needed) {
    return { ...base, status: 'unavailable', status_reason: `Only ${s.n} market days of history before this date; ${needed} needed for this horizon.` }
  }
  const t = H / 252
  const hist = s.mu * H
  const sigma = s.sigma * Math.sqrt(H) * (a.volatility_multiplier ?? 1)
  const rate = -((a.rate_change_bps ?? 0) / 100) * (RATE_SENS[id] ?? 0.01) * Math.min(1, t * 2)
  const earn = ((a.earnings_surprise_pct ?? 0) / 100) * 0.35 * Math.min(1, 63 / H + 0.3)
  const mkt = ((a.market_return_shift_pct ?? 0) / 100) * 1.1 * t
  const target = latestTarget(id, asOfIso)
  const px = CLOSES[id][idx]
  const tgtRet = target ? (target / px - 1) * Math.min(1, t) : 0
  const w = a.analyst_weight ?? 0.25
  const analyst = target ? w * (tgtRet - hist) : 0
  const baseRet = hist + rate + earn + mkt + analyst
  const drivers: Record<string, number> = { history: round(hist, 5), rate_change: round(rate, 5), earnings_surprise: round(earn, 5), market_shift: round(mkt, 5), analyst_targets: round(analyst, 5) }
  const applied: string[] = []
  if (a.rate_change_bps) applied.push(`Fed funds ${a.rate_change_bps > 0 ? '+' : ''}${a.rate_change_bps} bps`)
  if (a.earnings_surprise_pct) applied.push(`Earnings surprise ${a.earnings_surprise_pct > 0 ? '+' : ''}${a.earnings_surprise_pct}%`)
  if (a.market_return_shift_pct) applied.push(`Market return shift ${a.market_return_shift_pct > 0 ? '+' : ''}${a.market_return_shift_pct}%`)
  if ((a.volatility_multiplier ?? 1) !== 1) applied.push(`Volatility x${a.volatility_multiplier}`)
  applied.push(target ? `Analyst target weight ${Math.round(w * 100)}%` : 'No analyst target available')
  applied.push(`History: last ${a.lookback_years ?? 5} years`)
  const mk = (scenario: ScenarioForecast['scenario'], q: number, z: number): ScenarioForecast => {
    const ret = Math.exp(baseRet - 0.5 * sigma * sigma + z * sigma) - 1
    const spread = sigma * 0.55
    return {
      scenario, quantile: q, projected_return: round(ret, 5), projected_price: round(px * (1 + ret), 2),
      interval_low: round(px * Math.exp(baseRet + z * sigma - Z90 * spread), 2),
      interval_high: round(px * Math.exp(baseRet + z * sigma + Z90 * spread), 2),
      interval_coverage: 0.8, probability: null, assumptions_applied: applied,
    }
  }
  let status: SecurityForecast['status'] = h === 'short' ? 'medium' : h === 'medium' ? 'medium' : 'low'
  let reason: string | null = h === 'long' ? 'Two-year views rest on few independent periods; treat the range as rough.' : null
  if (id === 'GS' && h === 'long') {
    status = 'low'
    reason = 'Few comparable rate cycles in the synthetic history; wide uncertainty.'
  }
  if ((a.volatility_multiplier ?? 1) >= 2.5) {
    status = 'low'
    reason = 'Volatility multiplier is far outside history; the bands are a stress view, not an estimate.'
  }
  return { ...base, scenarios: [mk('optimistic', 0.9, Z90), mk('base', 0.5, 0), mk('pessimistic', 0.1, -Z90)], status, status_reason: reason, drivers }
}

function round(x: number, d: number): number {
  const f = 10 ** d
  return Math.round(x * f) / f
}

export function computeForecast(req: ForecastRequest, persist = true): ForecastRun {
  const asOfIso = resolveAsOf(req.as_of ?? null)
  const idx = asOfIndex(asOfIso)
  const a = assumeOf(req.assumptions)
  const horizons = req.horizons?.length ? req.horizons : (['short', 'medium', 'long'] as Horizon[])
  const forecasts: SecurityForecast[] = []
  for (const id of req.security_ids) for (const h of horizons) forecasts.push(forecastOne(id, h, a, idx, asOfIso))
  const runId = nextId('run-fc')
  const out: ForecastRun = {
    run_id: runId, as_of: asOfIso, data_cutoff: asOfIso, security_ids: req.security_ids, horizons, assumptions: a,
    forecasts, model_version: MODEL_VERSION, input_hash: mockHash({ req, asOfIso }), created_at: nowIso(),
  }
  if (persist) record('forecast', runId, req as unknown as Record<string, unknown>, asOfIso, out)
  return out
}

// ---------------------------------------------------------------- portfolio

export function validatePortfolio(p: Portfolio): FeasibilityIssue[] {
  const issues: FeasibilityIssue[] = []
  const c = consOf(p.constraints)
  const known = new Set(SECURITIES.filter((s) => s.investable).map((s) => s.security_id))
  const sum = p.holdings.reduce((a, h) => a + h.weight, 0)
  if (Math.abs(sum - 1) > 1e-4) {
    issues.push({ code: 'weights_sum', message: `Weights add up to ${(sum * 100).toFixed(1)}%. They must add up to 100%.`, field: 'holdings' })
  }
  const seen = new Set<string>()
  p.holdings.forEach((h, i) => {
    if (!known.has(h.security_id)) issues.push({ code: 'unknown_security', message: `${h.security_id || 'This row'} is not an investable security.`, field: `holdings.${i}.security_id` })
    if (seen.has(h.security_id)) issues.push({ code: 'duplicate_security', message: `${h.security_id} is listed twice.`, field: `holdings.${i}.security_id` })
    seen.add(h.security_id)
    if (h.security_id !== 'CASH' && h.weight > c.max_position_weight + 1e-9) {
      issues.push({ code: 'max_position', message: `${h.security_id} is ${(h.weight * 100).toFixed(1)}%, above the ${(c.max_position_weight * 100).toFixed(0)}% position limit.`, field: `holdings.${i}.weight` })
    }
  })
  if (c.min_cash_weight > c.max_cash_weight) {
    issues.push({ code: 'cash_bounds', message: 'Minimum cash is above maximum cash. No portfolio can meet both.', field: 'constraints.min_cash_weight' })
  }
  const cash = p.holdings.filter((h) => h.security_id === 'CASH').reduce((a, h) => a + h.weight, 0)
  if (cash < c.min_cash_weight - 1e-9) issues.push({ code: 'cash_bounds', message: `Cash is ${(cash * 100).toFixed(1)}%, below the ${(c.min_cash_weight * 100).toFixed(0)}% minimum.`, field: 'constraints.min_cash_weight' })
  if (cash > c.max_cash_weight + 1e-9) issues.push({ code: 'cash_bounds', message: `Cash is ${(cash * 100).toFixed(1)}%, above the ${(c.max_cash_weight * 100).toFixed(0)}% maximum.`, field: 'constraints.max_cash_weight' })
  const nonCash = known.size - 1
  if (c.max_position_weight * nonCash + c.max_cash_weight < 1 - 1e-9) {
    issues.push({ code: 'max_position', message: 'The position and cash limits together cannot reach 100%.', field: 'constraints.max_position_weight' })
  }
  return issues
}

function metricsFor(weights: Record<string, number>, h: Horizon, a: ScenarioAssumptions, idx: number, asOfIso: string, cashYield: number, covLookbackDays?: number) {
  const H = horizonDays(h)
  const ids = Object.keys(weights).filter((k) => weights[k] > 0)
  const cov = covariance(ids, idx, covLookbackDays ?? Math.round((a.lookback_years ?? 5) * 252))
  const w = ids.map((k) => weights[k])
  let variance = 0
  ids.forEach((_, i) => ids.forEach((__, j) => (variance += w[i] * w[j] * cov[i][j])))
  const sigma = Math.sqrt(Math.max(variance, 0) * H) * (a.volatility_multiplier ?? 1)
  let mu = 0
  ids.forEach((id, i) => {
    if (id === 'CASH') mu += w[i] * cashYield * (H / 252)
    else {
      const f = forecastOne(id, h === 'long' ? 'medium' : h, a, idx, asOfIso)
      const base = (f.scenarios ?? []).find((s) => s.scenario === 'base')
      const r = base ? Math.log(1 + base.projected_return) * (h === 'long' ? H / horizonDays('medium') : 1) : stats(id, idx, 1260).mu * H
      mu += w[i] * r
    }
  })
  const hhi = ids.reduce((s, k) => s + weights[k] ** 2, 0)
  const largest = ids.filter((k) => k !== 'CASH').sort((x, y) => weights[y] - weights[x])[0] ?? null
  const m: RiskMetrics = {
    horizon: h, horizon_trading_days: H,
    expected_return: round(mu, 5), volatility: round(sigma, 5),
    var_95: round(Math.max(0, -mu + 1.6449 * sigma), 5),
    cvar_95: round(Math.max(0, -mu + (sigma * phi(1.6449)) / 0.05), 5),
    max_drawdown_est: round(Math.min(0.95, 1.1 * sigma * Math.sqrt(Math.log(2 + H / 20)) * 0.75), 5),
    prob_loss_exceeds: { '0.05': round(Phi((-0.05 - mu) / Math.max(sigma, 1e-9)), 4), '0.1': round(Phi((-0.1 - mu) / Math.max(sigma, 1e-9)), 4) },
    concentration_hhi: round(hhi, 4), largest_position: largest, largest_weight: largest ? round(weights[largest], 4) : 0,
    cash_weight: round(weights.CASH ?? 0, 4),
  }
  return m
}

function scenarioPnl(m: RiskMetrics, value: number): ScenarioPnL[] {
  const rows: Array<[ScenarioPnL['scenario'], number]> = [['optimistic', Z90], ['base', 0], ['pessimistic', -Z90]]
  return rows.map(([scenario, z]) => {
    const r = round(Math.exp(m.expected_return + z * m.volatility) - 1, 5)
    return { scenario, return_pct: r, pnl: round(r * value, 2) }
  })
}

function weightsOf(p: Portfolio): Record<string, number> {
  const w: Record<string, number> = {}
  for (const h of p.holdings) w[h.security_id] = (w[h.security_id] ?? 0) + h.weight
  return w
}

function allocation(label: string, weights: Record<string, number>, current: Record<string, number>, p: Portfolio, a: ScenarioAssumptions, idx: number, asOfIso: string, notes: string[]): Allocation {
  const c = consOf(p.constraints)
  const m = metricsFor(weights, p.horizon ?? 'medium', a, idx, asOfIso, c.cash_annual_yield)
  const keys = new Set([...Object.keys(weights), ...Object.keys(current)])
  let turnover = 0
  keys.forEach((k) => (turnover += Math.abs((weights[k] ?? 0) - (current[k] ?? 0))))
  turnover = round(turnover / 2, 4)
  return {
    label, weights: Object.fromEntries(Object.entries(weights).map(([k, v]) => [k, round(v, 4)])), metrics: m,
    scenario_pnl: scenarioPnl(m, p.total_value), turnover, est_cost: round(turnover * 2 * p.total_value * (c.transaction_cost_bps / 1e4), 2), notes,
  }
}

function correlation(ids: string[], idx: number): Record<string, Record<string, number>> {
  const xs = ids.filter((i) => i !== 'CASH')
  const cov = covariance(xs, idx, 1260)
  const out: Record<string, Record<string, number>> = {}
  xs.forEach((a, i) => {
    out[a] = {}
    xs.forEach((b, j) => (out[a][b] = round(cov[i][j] / Math.sqrt(cov[i][i] * cov[j][j]), 3)))
  })
  return out
}

function capped(base: Record<string, number>, cashTarget: number, cap: number): Record<string, number> {
  const nonCash = Object.entries(base).filter(([k]) => k !== 'CASH')
  const total = nonCash.reduce((s, [, v]) => s + v, 0) || 1
  const out: Record<string, number> = { CASH: cashTarget }
  nonCash.forEach(([k, v]) => (out[k] = Math.min(cap, (v / total) * (1 - cashTarget))))
  const spill = 1 - Object.values(out).reduce((s, v) => s + v, 0)
  out.CASH += spill
  return out
}

export function evaluatePortfolio(req: PortfolioRequest, optimize: boolean, persist = true): PortfolioEvaluation {
  const asOfIso = resolveAsOf(req.as_of ?? null)
  const idx = asOfIndex(asOfIso)
  const p = req.portfolio
  const a = assumeOf(req.assumptions)
  const runId = nextId(optimize ? 'run-opt' : 'run-pf')
  const issues = validatePortfolio(p)
  const ids = SECURITIES.filter((s) => s.investable).map((s) => s.security_id)
  const out: PortfolioEvaluation = {
    run_id: runId, as_of: asOfIso, portfolio_id: p.portfolio_id ?? 'default', feasible: issues.length === 0, issues,
    current: null, candidates: [], correlation: correlation(ids, idx), model_version: MODEL_VERSION,
    input_hash: mockHash({ req, asOfIso }), disclaimer: DECISION_BOUNDARY,
  }
  if (issues.length === 0) {
    const cur = weightsOf(p)
    out.current = allocation('current', cur, cur, p, a, idx, asOfIso, ['Your holdings as entered.'])
    if (optimize) {
      const c = consOf(p.constraints)
      const clampCash = (x: number) => Math.min(c.max_cash_weight, Math.max(c.min_cash_weight, x))
      const eq: Record<string, number> = { JPM: 0.2, BAC: 0.2, C: 0.2, MS: 0.2, GS: 0.2 }
      const cands: Array<[string, Record<string, number>, string[]]> = [
        ['no change', cur, ['Keeps today’s weights. No cost, full exposure to the scenarios.']],
        ['balanced', capped(eq, clampCash(Math.max(cur.CASH ?? 0, 0.05)), c.max_position_weight), ['Spreads the bank exposure evenly within the position limit.']],
        ['min risk', capped(cur, clampCash(0.3), c.max_position_weight), ['Lower volatility by holding 30% cash. Gives up some upside.']],
        ['defensive', capped(cur, clampCash(0.5), c.max_position_weight), ['Half in cash. Cash still carries rate and inflation risk.']],
      ]
      out.candidates = cands.map(([label, w, notes]) => {
        const alloc = allocation(label, w, cur, p, a, idx, asOfIso, notes)
        if (c.max_turnover != null && (alloc.turnover ?? 0) > c.max_turnover) alloc.notes?.push(`Turnover ${((alloc.turnover ?? 0) * 100).toFixed(0)}% is above your ${(c.max_turnover * 100).toFixed(0)}% limit.`)
        return alloc
      })
    }
  }
  if (persist) record(optimize ? 'optimize' : 'portfolio', runId, req as unknown as Record<string, unknown>, asOfIso, out)
  return out
}

// ---------------------------------------------------------------- impact

export function impactFor(eventId: string, asOfIso: string): ImpactEstimate[] | null {
  const raw = EVENTS.find((e) => e.event_id === eventId)
  if (!raw) return null
  const e = eventAsOf(raw, asOfIso)
  if (!e) return null
  const idxAsOf = asOfIndex(asOfIso)
  return e.affected_security_ids.map((sec) => {
    const when = (e.occurred_at ?? e.scheduled_at ?? e.available_at).slice(0, 10)
    const i0 = dayIndexAtOrBefore(when)
    const realized = e.status !== 'upcoming' && i0 + 3 <= idxAsOf
    const sameType = EVENTS.filter((x) => x.subtype === e.subtype && x.affected_security_ids.includes(sec) && (x.occurred_at ?? '') < (e.occurred_at ?? e.scheduled_at ?? asOfIso))
    const common = { event_id: e.event_id, security_id: sec, window_pre_days: 1, window_post_days: 3, benchmark_id: 'XLF', as_of: asOfIso, evidence_ids: [e.event_id] }
    if (!realized) {
      const cars = sameType.slice(-12).map((x) => carAt(sec, dayIndexAtOrBefore((x.occurred_at as string).slice(0, 10))).car)
      if (cars.length < 4) {
        return { ...common, realized: false, direction: 'unknown', method: 'mean_past_car_same_subtype', sample_size: cars.length, confidence: 'unavailable', note: `Only ${cars.length} similar past events; not enough to estimate a forward impact.` } as ImpactEstimate
      }
      const m = cars.reduce((a, b) => a + b, 0) / cars.length
      const sd = Math.sqrt(cars.reduce((a, b) => a + (b - m) ** 2, 0) / (cars.length - 1))
      return { ...common, realized: false, direction: Math.abs(m) < 0.003 ? 'neutral' : m > 0 ? 'up' : 'down', expected_return_impact: round(m, 5), uncertainty: round(sd, 5), duration_days: 3, method: 'mean_past_car_same_subtype', sample_size: cars.length, confidence: 'low', probability: null, note: 'Association, not proven causation. Forward estimate from past similar events.' } as ImpactEstimate
    }
    const { car, day0, drift, t } = carAt(sec, i0)
    const conf = Math.abs(t) > 2.5 ? 'high' : Math.abs(t) > 1.5 ? 'medium' : 'low'
    return { ...common, realized: true, direction: Math.abs(car) < 0.003 ? 'neutral' : car > 0 ? 'up' : 'down', abnormal_return: round(car, 5), event_day_return: round(day0, 5), post_event_drift: round(drift, 5), t_stat: round(t, 2), duration_days: 3, method: 'market_model_car_vs_XLF', sample_size: 250, confidence: conf, probability: null, note: 'Association, not proven causation.' } as ImpactEstimate
  })
}

function carAt(sec: string, i0: number) {
  const r = RETURNS[sec]
  const b = RETURNS.XLF
  const est = Math.max(1, i0 - 260)
  const resid: number[] = []
  for (let k = est; k < i0 - 10; k++) resid.push(r[k] - b[k])
  const sd = Math.sqrt(resid.reduce((a, x) => a + x * x, 0) / Math.max(resid.length - 1, 1)) || 0.01
  let car = 0
  for (let k = i0 - 1; k <= Math.min(i0 + 3, r.length - 1); k++) car += r[k] - b[k]
  const day0 = r[i0] - b[i0]
  return { car, day0, drift: car - day0, t: car / (sd * Math.sqrt(5)) }
}

// ---------------------------------------------------------------- alerts

function alternatives(p: Portfolio, h: Horizon, a: ScenarioAssumptions, idx: number, asOfIso: string): ActionOption[] {
  const cur = weightsOf(p)
  const c = consOf(p.constraints)
  const base = metricsFor(cur, h, a, idx, asOfIso, c.cash_annual_yield)
  const baseOpt = Math.exp(base.expected_return + Z90 * base.volatility) - 1
  return ([['Hold (no change)', 0], ['Move 25% to cash', 0.25], ['Move 50% to cash', 0.5]] as Array<[string, number]>).map(([label, shift]) => {
    const w: Record<string, number> = {}
    Object.entries(cur).forEach(([k, v]) => (w[k] = k === 'CASH' ? v : v * (1 - shift)))
    w.CASH = (cur.CASH ?? 0) + (1 - (cur.CASH ?? 0)) * shift
    const m = metricsFor(w, h, a, idx, asOfIso, c.cash_annual_yield)
    const opt = Math.exp(m.expected_return + Z90 * m.volatility) - 1
    const moved = (1 - (cur.CASH ?? 0)) * shift
    return {
      label, weights: Object.fromEntries(Object.entries(w).map(([k, v]) => [k, round(v, 4)])), expected_return: m.expected_return, cvar_95: m.cvar_95,
      projected_loss: round(m.cvar_95 * p.total_value, 2), est_cost: round(moved * p.total_value * (c.transaction_cost_bps / 1e4), 2),
      missed_upside: round(Math.max(0, baseOpt - opt) * p.total_value, 2),
      note: shift === 0 ? 'Keeps full exposure. No cost.' : `Lower loss in the bad case; gives up some recovery if prices rebound. Cash yield assumed ${(c.cash_annual_yield * 100).toFixed(1)}% a year.`,
    }
  })
}

/** Alert rules look at recent (about 3 months) volatility so they react to shocks. */
const RECENT_DAYS = 63

const SEV_RANK: Record<AlertSeverity, number> = { info: 0, warning: 1, high: 2, critical: 3 }
function asSeverity(s: string): AlertSeverity {
  return (['info', 'warning', 'high', 'critical'] as const).includes(s as AlertSeverity) ? (s as AlertSeverity) : 'warning'
}

function evidenceFor(p: Portfolio, idx: number, asOfIso: string, extra: EvidenceItem[] = []): { evidence: EvidenceItem[]; triggering: string[] } {
  const since = DAYS[Math.max(0, idx - 15)]
  const held = new Set(p.holdings.map((h) => h.security_id))
  const evts = EVENTS.map((e) => eventAsOf(e, asOfIso)).filter((e): e is NonNullable<typeof e> => !!e && (e.occurred_at ?? '') >= since && e.affected_security_ids.some((s) => held.has(s)) && !e.canonical_event_id)
  const evidence: EvidenceItem[] = evts.slice(-4).map((e) => ({ kind: 'event', ref_id: e.event_id, label: e.title, at: e.occurred_at ?? e.scheduled_at ?? null, origin: e.origin ?? 'synthetic', url: null }))
  const an = ANALYSTS.filter((x) => held.has(x.security_id) && x.available_at <= asOfIso).slice(-2)
  an.forEach((x) => evidence.push({ kind: 'analyst', ref_id: x.observation_id, label: `${x.analyst_source}: ${x.security_id} ${x.action.replace('_', ' ')}${x.target_price ? `, target $${x.target_price}` : ''}`, at: x.issued_at, origin: 'synthetic', url: null }))
  evidence.push({ kind: 'price', ref_id: `px-${DAYS[idx]}`, label: `Closing prices up to ${DAYS[idx]}`, at: `${DAYS[idx]}T21:00:00Z`, origin: 'synthetic', url: null })
  evidence.push({ kind: 'macro', ref_id: `dff-${DAYS[idx]}`, label: `Fed funds effective rate ${dffAt(DAYS[idx]).toFixed(2)}%`, at: `${DAYS[idx]}T21:15:00Z`, origin: 'synthetic', url: null })
  evidence.push(...extra)
  return { evidence, triggering: evts.slice(-4).map((e) => e.event_id) }
}

export function evaluateRules(p: Portfolio, a: ScenarioAssumptions, asOfIso: string, runId: string, ruleIds: string[] | null, cooldown: Map<string, number> | null): Alert[] {
  const idx = asOfIndex(asOfIso)
  const rules = db.settings.alert_rules.filter((r) => r.enabled !== false && (!ruleIds || ruleIds.includes(r.rule_id)))
  const w = weightsOf(p)
  const c = consOf(p.constraints)
  const out: Alert[] = []
  for (const r of rules) {
    if (cooldown) {
      const last = cooldown.get(r.rule_id)
      if (last !== undefined && idx - last < (r.cooldown_trading_days ?? 5)) continue
    }
    const h = r.horizon ?? 'short'
    const m = metricsFor(w, h, a, idx, asOfIso, c.cash_annual_yield, RECENT_DAYS)
    let value = 0
    let title = ''
    let summary = ''
    let prob: number | null = null
    let realizedNote: string | null = null
    if (r.metric === 'forecast_drawdown') {
      value = m.cvar_95
      title = `Simulated loss in the worst 5% of outcomes is ${(value * 100).toFixed(1)}%`
      summary = `Over the next ${m.horizon_trading_days} market days, the average loss in the worst 5% of simulated paths is ${(value * 100).toFixed(1)}%, above your ${(r.threshold * 100).toFixed(0)}% rule. This is a forecast, not a realized loss.`
      prob = m.prob_loss_exceeds?.['0.05'] ?? null
    } else if (r.metric === 'downside_probability') {
      const key = String(r.loss_level ?? 0.05)
      value = m.prob_loss_exceeds?.[key] ?? m.prob_loss_exceeds?.['0.05'] ?? 0
      prob = value
      title = `Chance of losing more than ${((r.loss_level ?? 0.05) * 100).toFixed(0)}% is ${(value * 100).toFixed(0)}% (simulated)`
      summary = `Simulated, uncalibrated probability over ${m.horizon_trading_days} market days. Your rule triggers at ${(r.threshold * 100).toFixed(0)}%.`
    } else if (r.metric === 'realized_loss') {
      const lb = r.lookback_trading_days ?? 10
      const v0 = portfolioValueAt(p, idx - lb)
      const v1 = portfolioValueAt(p, idx)
      value = Math.max(0, 1 - v1 / v0)
      title = `Portfolio is down ${(value * 100).toFixed(1)}% over ${lb} market days`
      summary = `This is an actual (realized) change in value, measured from synthetic closing prices, not a forecast.`
      realizedNote = 'Realized loss uses closing prices only; intraday moves are not seen.'
    } else if (r.metric === 'concentration') {
      value = m.largest_weight ?? 0
      title = `${m.largest_position} is ${(value * 100).toFixed(0)}% of the portfolio`
      summary = `The largest single position is above your ${(r.threshold * 100).toFixed(0)}% concentration rule.`
    } else if (r.metric === 'event_severity') {
      const since = DAYS[Math.max(0, idx - 5)]
      let worst = 0
      for (const e of EVENTS) {
        const ev = eventAsOf(e, asOfIso)
        if (!ev || (ev.occurred_at ?? '') < since || ev.status === 'upcoming') continue
        for (const s of ev.affected_security_ids) if (w[s]) worst = Math.max(worst, Math.abs(carAt(s, dayIndexAtOrBefore((ev.occurred_at as string).slice(0, 10))).car))
      }
      value = worst
      title = `A recent event moved a holding by ${(value * 100).toFixed(1)}% versus its sector`
      summary = 'Abnormal return after a recent event exceeded your rule. Association, not causation.'
    }
    if (value <= r.threshold) continue
    if (cooldown) cooldown.set(r.rule_id, idx)
    const { evidence, triggering } = evidenceFor(p, idx, asOfIso, [{ kind: 'model', ref_id: runId, label: `Model ${MODEL_VERSION}, ${m.horizon_trading_days}-day horizon`, at: asOfIso, origin: 'synthetic', url: null }])
    const sev = asSeverity(r.severity ?? 'warning')
    const bump = value > r.threshold * 1.6 && SEV_RANK[sev] < 3 ? (['info', 'warning', 'high', 'critical'] as const)[SEV_RANK[sev] + 1] : sev
    const affected = Object.keys(w).filter((k) => k !== 'CASH' && w[k] > 0)
    const exp = new Date(asOfIso)
    exp.setUTCDate(exp.getUTCDate() + 7)
    out.push({
      alert_id: nextId('alt'), run_id: runId, portfolio_id: p.portfolio_id ?? 'default', rule_id: r.rule_id, rule_version: r.version ?? 1, severity: bump, status: 'new', as_of: asOfIso,
      horizon: h, horizon_trading_days: m.horizon_trading_days, title, summary, triggering_event_ids: triggering, affected_security_ids: affected,
      current_exposure: Object.fromEntries(Object.entries(w).map(([k, v]) => [k, round(v * p.total_value, 2)])),
      metric_value: round(value, 5), threshold: r.threshold,
      projected_loss: r.metric === 'realized_loss' ? round(value * p.total_value, 2) : round(m.cvar_95 * p.total_value, 2),
      projected_loss_pct: r.metric === 'realized_loss' ? round(value, 5) : m.cvar_95, probability: prob,
      confidence: r.metric === 'realized_loss' || r.metric === 'concentration' ? 'high' : 'low',
      limitations: [
        'All data is synthetic. Numbers show how the workflow behaves, not real market risk.',
        'Probabilities are simulated from a normal model and are not calibrated.',
        'Correlations are estimated from history and can rise sharply in a crisis.',
        ...(realizedNote ? [realizedNote] : []),
      ],
      evidence, alternatives: alternatives(p, h, a, idx, asOfIso), expires_at: exp.toISOString().replace('.000', ''), superseded_by: null,
      decision_boundary: DECISION_BOUNDARY,
    })
  }
  return out
}

export function portfolioValueAt(p: Portfolio, i: number): number {
  const i0 = Math.max(0, i)
  let v = 0
  for (const h of p.holdings) {
    if (h.security_id === 'CASH' || !CLOSES[h.security_id]) v += h.weight * p.total_value
    else v += h.weight * p.total_value * (CLOSES[h.security_id][i0] / CLOSES[h.security_id][DAYS.length - 1])
  }
  return v
}

export function runAlerts(p: Portfolio, a: ScenarioAssumptions, asOfIso: string, ruleIds: string[] | null): { runId: string; alerts: Alert[] } {
  const runId = nextId('run-al')
  const alerts = evaluateRules(p, assumeOf(a), asOfIso, runId, ruleIds, null)
  record('alerts', runId, { portfolio: p, assumptions: a, rule_ids: ruleIds, as_of: asOfIso }, asOfIso, alerts)
  supersede(alerts)
  db.alerts.unshift(...alerts)
  return { runId, alerts }
}

function supersede(fresh: Alert[]) {
  for (const n of fresh) {
    for (const old of db.alerts) {
      if (old.rule_id === n.rule_id && (old.status === 'new' || old.status === 'acknowledged')) {
        old.status = 'superseded'
        old.superseded_by = n.alert_id
      }
    }
  }
}

export function runReplay(req: ReplayRequest, persist = true): ReplayResult {
  const runId = nextId('run-rp')
  const a = assumeOf(req.assumptions)
  const s = dayIndexAtOrBefore(req.start)
  const e = dayIndexAtOrBefore(req.end)
  const step = Math.max(1, Math.min(20, req.step_trading_days ?? 1))
  // Rebase the replay portfolio so total_value is the value on the start date.
  const scale = req.portfolio.total_value / portfolioValueAt(req.portfolio, s)
  const p = { ...req.portfolio }
  const frames: ReplayFrame[] = []
  const alerts: Alert[] = []
  const cooldown = new Map<string, number>()
  for (let i = s; i <= e; i += step) {
    const asOfIso = new Date(`${DAYS[i]}T23:59:00-05:00`).toISOString().replace('.000', '')
    const fired = evaluateRules(p, a, asOfIso, runId, req.rule_ids ?? null, cooldown)
    fired.forEach((x) => {
      x.limitations = [...(x.limitations ?? []), 'Raised during a historical replay; it was not sent at the time.']
      if (x.projected_loss != null) x.projected_loss = round(x.projected_loss * scale, 2)
      x.current_exposure = Object.fromEntries(Object.entries(x.current_exposure ?? {}).map(([k, v]) => [k, round(v * scale, 2)]))
    })
    alerts.push(...fired)
    frames.push({ as_of: DAYS[i], portfolio_value: round(portfolioValueAt(p, i) * scale, 2), metrics: null, new_alert_ids: fired.map((x) => x.alert_id), limitations: [] })
  }
  const out: ReplayResult = { run_id: runId, start: DAYS[s], end: DAYS[e], frames, alerts, model_version: MODEL_VERSION, input_hash: mockHash({ req }), mode: 'replay' }
  if (persist) {
    record('replay', runId, req as unknown as Record<string, unknown>, resolveAsOf(DAYS[e]), out)
    db.alerts.unshift(...[...alerts].reverse())
  }
  return out
}

export function reproduce(runId: string): ReproduceResult | null {
  const rec = db.runs.find((r) => r.run_id === runId)
  if (!rec) return null
  const req = rec.request as Record<string, unknown>
  let out: unknown
  const seq = db.seq
  if (rec.kind === 'forecast') out = computeForecast(req as unknown as ForecastRequest, false)
  else if (rec.kind === 'portfolio' || rec.kind === 'optimize') out = evaluatePortfolio(req as unknown as PortfolioRequest, rec.kind === 'optimize', false)
  else if (rec.kind === 'replay') out = runReplay(req as unknown as ReplayRequest, false)
  else out = evaluateRules(req.portfolio as Portfolio, assumeOf(req.assumptions as ScenarioAssumptions | undefined), rec.as_of ?? LATEST_ISO, rec.run_id, (req.rule_ids as string[] | null) ?? null, null)
  db.seq = seq
  const h = outputHash(out)
  return { run_id: runId, reproduced_run_id: `${runId}-r`, original_output_hash: rec.output_hash, reproduced_output_hash: h, match: h === rec.output_hash, note: h === rec.output_hash ? 'Same request, same as_of and same data cutoff gave the same output.' : 'Output differs. Check whether settings or source data changed.' }
}

// ---------------------------------------------------------------- seed

function seedAlerts() {
  const p = DEFAULT_PORTFOLIO
  // A replay over the synthetic April 2025 shock seeds the inbox with realistic alerts.
  runReplay({ portfolio: p, start: '2025-03-24', end: '2025-04-17', step_trading_days: 1, rule_ids: null, assumptions: DEFAULT_ASSUMPTIONS })
  const seeded = db.alerts
  if (seeded[1]) seeded[1].status = 'acknowledged'
  if (seeded[2]) seeded[2].status = 'resolved'
  // Make sure the inbox has one item at the latest date as well.
  runAlerts({ ...p, holdings: [{ security_id: 'JPM', weight: 0.5 }, { security_id: 'BAC', weight: 0.3 }, { security_id: 'CASH', weight: 0.2 }], constraints: { ...DEFAULT_CONSTRAINTS, max_position_weight: 0.6 } }, DEFAULT_ASSUMPTIONS, LATEST_ISO, ['concentration'])
  void BANKS
}

seedAlerts()
