/**
 * Deterministic SYNTHETIC market data for the mock API. Nothing here is real market data:
 * prices come from a seeded random walk, events and analyst views are invented, and every
 * response that uses them carries `data_origin: "synthetic"`.
 */
import type {
  AnalystObservation,
  Event,
  EventClass,
  EventScope,
  Observation,
  Security,
  SourceStatus,
} from '../api/types'

export const MOCK_VERSION = '0.1.0-mock'
export const MODEL_VERSION = 'mock-scenario-0.1'
export const LATEST = '2025-11-21'
export const LATEST_ISO = '2025-11-22T04:59:00Z' // 23:59 New York on LATEST
export const DECISION_BOUNDARY =
  'ForwardState is decision support only. It does not trade, route orders or move money. You decide whether and how to act.'

export const BANKS = ['JPM', 'BAC', 'C', 'MS', 'GS'] as const
export const BENCHMARKS = ['SPY', 'XLF'] as const

export const SECURITIES: Security[] = [
  { security_id: 'JPM', ticker: 'JPM', name: 'JPMorgan Chase & Co.', sector: 'financials', currency: 'USD', role: 'focal', investable: true },
  { security_id: 'BAC', ticker: 'BAC', name: 'Bank of America Corp.', sector: 'financials', currency: 'USD', role: 'peer', investable: true },
  { security_id: 'C', ticker: 'C', name: 'Citigroup Inc.', sector: 'financials', currency: 'USD', role: 'peer', investable: true },
  { security_id: 'MS', ticker: 'MS', name: 'Morgan Stanley', sector: 'financials', currency: 'USD', role: 'peer', investable: true },
  { security_id: 'GS', ticker: 'GS', name: 'Goldman Sachs Group Inc.', sector: 'financials', currency: 'USD', role: 'peer', investable: true },
  { security_id: 'SPY', ticker: 'SPY', name: 'S&P 500 ETF (benchmark)', sector: 'market', currency: 'USD', role: 'benchmark', investable: false },
  { security_id: 'XLF', ticker: 'XLF', name: 'Financials sector ETF (benchmark)', sector: 'financials', currency: 'USD', role: 'benchmark', investable: false },
  { security_id: 'CASH', ticker: 'CASH', name: 'Cash (USD)', sector: 'cash', currency: 'USD', role: 'defensive', investable: true },
]

// ---------------------------------------------------------------- random

export function mulberry32(seed: number) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function normalGen(rand: () => number) {
  return () => {
    const u = Math.max(rand(), 1e-12)
    const v = rand()
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v)
  }
}

// ---------------------------------------------------------------- calendar

function iso(d: Date): string {
  return d.toISOString().slice(0, 10)
}

function buildTradingDays(start: string, end: string): string[] {
  const out: string[] = []
  const d = new Date(`${start}T00:00:00Z`)
  const e = new Date(`${end}T00:00:00Z`)
  while (d <= e) {
    const wd = d.getUTCDay()
    if (wd !== 0 && wd !== 6) out.push(iso(d))
    d.setUTCDate(d.getUTCDate() + 1)
  }
  return out
}

export const DAYS = buildTradingDays('2018-01-02', LATEST)
export const DAY_INDEX = new Map(DAYS.map((d, i) => [d, i]))

/** Index of the last trading day on or before `d`. */
export function dayIndexAtOrBefore(d: string): number {
  let lo = 0
  let hi = DAYS.length - 1
  if (d < DAYS[0]) return -1
  if (d >= DAYS[hi]) return hi
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (DAYS[mid] <= d) lo = mid
    else hi = mid - 1
  }
  return lo
}

// ---------------------------------------------------------------- prices

interface Params {
  start: number
  drift: number
  idio: number
  betaM: number
  betaF: number
}

const PARAMS: Record<string, Params> = {
  JPM: { start: 104, drift: 0.00035, idio: 0.009, betaM: 1.05, betaF: 1.0 },
  BAC: { start: 29, drift: 0.00018, idio: 0.011, betaM: 1.15, betaF: 1.15 },
  C: { start: 75, drift: 0.00002, idio: 0.013, betaM: 1.25, betaF: 1.2 },
  MS: { start: 52, drift: 0.0004, idio: 0.012, betaM: 1.2, betaF: 0.95 },
  GS: { start: 235, drift: 0.00038, idio: 0.012, betaM: 1.15, betaF: 0.9 },
  SPY: { start: 268, drift: 0.0002, idio: 0.0015, betaM: 1.0, betaF: 0.0 },
  XLF: { start: 29, drift: 0.0001, idio: 0.003, betaM: 1.0, betaF: 0.9 },
}

/** Annual log-return trend each synthetic path is pulled to. */
const TREND: Record<string, number> = { JPM: 0.13, BAC: 0.07, C: 0.035, MS: 0.11, GS: 0.115, SPY: 0.11, XLF: 0.075 }

/** Synthetic shocks that the replay and event studies can find. */
const MARKET_SHOCKS: Record<string, number> = {
  '2020-02-24': -0.035, '2020-02-27': -0.045, '2020-03-09': -0.075, '2020-03-12': -0.09,
  '2020-03-16': -0.11, '2020-03-18': -0.05, '2020-03-24': 0.085, '2020-03-26': 0.06,
  '2022-06-13': -0.038, '2025-04-03': -0.048, '2025-04-04': -0.058, '2025-04-07': -0.02,
  '2025-04-09': 0.085,
}
const FIN_SHOCKS: Record<string, number> = {
  '2023-03-09': -0.045, '2023-03-10': -0.035, '2023-03-13': -0.05, '2023-03-15': -0.03,
  '2023-03-16': 0.015, '2023-03-20': 0.02, '2025-04-04': -0.015,
}
const IDIO_SHOCKS: Record<string, Record<string, number>> = {
  C: { '2022-10-14': 0.06, '2024-04-12': -0.052 },
  GS: { '2023-10-17': -0.05 },
  MS: { '2024-01-16': -0.042 },
  JPM: { '2023-04-14': 0.075 },
}

export const CLOSES: Record<string, number[]> = {}
export const RETURNS: Record<string, number[]> = {}
;(() => {
  const nM = normalGen(mulberry32(7))
  const nF = normalGen(mulberry32(11))
  const mkt: number[] = []
  const fin: number[] = []
  for (const d of DAYS) {
    mkt.push(0.0003 + 0.0095 * nM() + (MARKET_SHOCKS[d] ?? 0))
    fin.push(0.0065 * nF() + (FIN_SHOCKS[d] ?? 0))
  }
  let seed = 101
  for (const [id, p] of Object.entries(PARAMS)) {
    const nI = normalGen(mulberry32(seed++))
    const closes: number[] = []
    const rets: number[] = []
    let px = p.start
    DAYS.forEach((d, i) => {
      const r = i === 0 ? 0 : p.drift + p.betaM * (mkt[i] - 0.0003) + p.betaF * fin[i] + p.idio * nI() + (IDIO_SHOCKS[id]?.[d] ?? 0)
      const rr = Math.max(r, -0.25)
      px = px * (1 + rr)
      closes.push(Math.round(px * 100) / 100)
      rets.push(rr)
    })
    // Keep the noise and shocks, but set the long-run trend to a plausible level per security.
    const years = (DAYS.length - 1) / 252
    const realised = Math.log(closes[closes.length - 1] / p.start)
    const adj = (TREND[id] * years - realised) / (DAYS.length - 1)
    let q = p.start
    const adjRets = rets.map((r, i) => (i === 0 ? 0 : (1 + r) * Math.exp(adj) - 1))
    CLOSES[id] = adjRets.map((r) => { q = q * (1 + r); return Math.round(q * 100) / 100 })
    RETURNS[id] = adjRets
  }
})()

/** Raw close differs from adjusted close by dividends paid after the bar (synthetic yield). */
export function rawClose(id: string, i: number): number {
  const yearsToLatest = (DAYS.length - 1 - i) / 252
  const yieldPa = id === 'SPY' ? 0.014 : id === 'XLF' ? 0.018 : 0.025
  return Math.round(CLOSES[id][i] * (1 + yieldPa * yearsToLatest) * 100) / 100
}

// ---------------------------------------------------------------- macro

/** Synthetic Fed funds target path (effective rate), changes take effect on the date. */
const DFF_PATH: Array<[string, number]> = [
  ['2018-01-02', 1.42], ['2018-03-22', 1.68], ['2018-06-14', 1.91], ['2018-09-27', 2.18], ['2018-12-20', 2.4],
  ['2019-08-01', 2.13], ['2019-09-19', 1.9], ['2019-10-31', 1.55], ['2020-03-04', 1.1], ['2020-03-16', 0.08],
  ['2022-03-17', 0.33], ['2022-05-05', 0.83], ['2022-06-16', 1.58], ['2022-07-28', 2.33], ['2022-09-22', 3.08],
  ['2022-11-03', 3.83], ['2022-12-15', 4.33], ['2023-02-02', 4.58], ['2023-03-23', 4.83], ['2023-05-04', 5.08],
  ['2023-07-27', 5.33], ['2024-09-19', 4.83], ['2024-11-08', 4.58], ['2024-12-19', 4.33], ['2025-09-18', 4.08],
  ['2025-10-30', 3.88],
]

export function dffAt(d: string): number {
  let v = DFF_PATH[0][1]
  for (const [k, x] of DFF_PATH) if (k <= d) v = x
  return v
}

export const FOMC_DATES: string[] = (() => {
  const md = ['01-31', '03-20', '05-02', '06-13', '07-31', '09-18', '10-30', '12-11']
  const out: string[] = []
  for (let y = 2018; y <= 2026; y++) {
    for (const m of md) {
      let d = `${y}-${m}`
      // Use the closest listed path change if within 3 days, so decisions line up with DFF.
      const near = DFF_PATH.find(([k]) => Math.abs(Date.parse(k) - Date.parse(d)) <= 3 * 864e5 * 4 && k.slice(0, 7) === d.slice(0, 7))
      if (near) d = near[0]
      out.push(d)
    }
  }
  return out.filter((d) => d <= '2026-03-31')
})()

function macroSeries(metric: 'DFF' | 'DGS2' | 'DGS10'): Observation[] {
  const n = normalGen(mulberry32(metric === 'DFF' ? 3 : metric === 'DGS2' ? 5 : 9))
  const out: Observation[] = []
  let noise = 0
  for (let i = 0; i < DAYS.length; i += 5) {
    const d = DAYS[i]
    const dff = dffAt(d)
    noise = 0.85 * noise + 0.08 * n()
    let v = dff
    if (metric === 'DGS2') v = dff + 0.15 + noise
    if (metric === 'DGS10') v = 2.1 + 0.42 * dff + noise * 1.4
    v = Math.max(0.05, Math.round(v * 100) / 100)
    const avail = new Date(`${d}T21:15:00Z`)
    avail.setUTCDate(avail.getUTCDate() + 1)
    out.push({
      source_id: 'fred',
      origin: 'synthetic',
      available_at: avail.toISOString().replace('.000', ''),
      availability_inferred: false,
      metric_id: metric,
      security_id: null,
      economy: 'US',
      period_end: d,
      value: v,
      unit: 'percent',
      release_at: avail.toISOString().replace('.000', ''),
      ingested_at: null,
      vintage: null,
    })
  }
  return out
}

export const MACRO: Observation[] = [...macroSeries('DFF'), ...macroSeries('DGS2'), ...macroSeries('DGS10')]

// ---------------------------------------------------------------- fundamentals & events

const EPS_BASE: Record<string, number> = { JPM: 2.35, BAC: 0.62, C: 1.6, MS: 1.05, GS: 6.0 }

function nextWeekday(d: string): string {
  const x = new Date(`${d}T00:00:00Z`)
  while (x.getUTCDay() === 0 || x.getUTCDay() === 6) x.setUTCDate(x.getUTCDate() + 1)
  return iso(x)
}

function addDays(d: string, n: number): string {
  const x = new Date(`${d}T00:00:00Z`)
  x.setUTCDate(x.getUTCDate() + n)
  return iso(x)
}

export const FUNDAMENTALS: Observation[] = []
export type MockEvent = Event & { affected_security_ids: string[]; origin: NonNullable<Event['origin']> }
export const EVENTS: MockEvent[] = []

;(() => {
  const rand = mulberry32(42)
  const quarterEnds = ['03-31', '06-30', '09-30', '12-31']
  const reportOffset = [14, 14, 14, 14]
  BANKS.forEach((id, bi) => {
    let eps = EPS_BASE[id]
    for (let y = 2018; y <= 2025; y++) {
      quarterEnds.forEach((qe, qi) => {
        const periodEnd = `${y}-${qe}`
        const repMonth = ['04', '07', '10', '01'][qi]
        const repYear = qi === 3 ? y + 1 : y
        const reportDate = nextWeekday(`${repYear}-${repMonth}-${String(reportOffset[qi] + (bi % 3)).padStart(2, '0')}`)
        if (reportDate > '2026-02-28') return
        eps = eps * (1 + 0.025 + (rand() - 0.5) * 0.12)
        const est = Math.round(eps * 100) / 100
        const surprisePct = (rand() - 0.42) * 0.14
        const actual = Math.round(est * (1 + surprisePct) * 100) / 100
        const releaseAt = `${reportDate}T11:45:00Z`
        const estAvailable = `${addDays(reportDate, -7)}T21:00:00Z`
        FUNDAMENTALS.push(
          {
            source_id: 'edgar', origin: 'synthetic', available_at: estAvailable, availability_inferred: true,
            metric_id: 'eps_estimate', security_id: id, economy: null, period_end: periodEnd, value: est,
            unit: 'usd_per_share', release_at: estAvailable, vintage: null, ingested_at: null,
          },
          {
            source_id: 'edgar', origin: 'synthetic', available_at: releaseAt, availability_inferred: false,
            metric_id: 'eps_actual', security_id: id, economy: null, period_end: periodEnd, value: actual,
            unit: 'usd_per_share', release_at: releaseAt, vintage: null, ingested_at: null,
          },
        )
        const q = qi + 1
        EVENTS.push({
          source_id: 'edgar', origin: 'synthetic', available_at: `${addDays(reportDate, -30)}T12:00:00Z`,
          availability_inferred: true, ingested_at: null,
          event_id: `evt-results-${id}-${y}q${q}`,
          event_class: 'scheduled', subtype: 'quarterly_results',
          title: `${id} Q${q} ${y} results`,
          status: 'occurred', scope: 'firm',
          scheduled_at: releaseAt, occurred_at: releaseAt, published_at: releaseAt,
          affected_security_ids: [id], source_ids: [`synthetic://edgar/${id}/${y}q${q}`],
          expected_outcome: `EPS estimate $${est.toFixed(2)}`,
          actual_outcome: `EPS $${actual.toFixed(2)}`,
          surprise: Math.round((actual - est) * 100) / 100,
          revision: 0, canonical_event_id: null,
        })
      })
    }
  })

  // FOMC meetings
  for (const d of FOMC_DATES) {
    const before = dffAt(addDays(d, -1))
    const after = dffAt(d)
    const bps = Math.round((after - before) * 100)
    const outcome = bps === 0 ? 'Target range unchanged' : bps > 0 ? `Raised ${bps} bps` : `Cut ${Math.abs(bps)} bps`
    const at = `${d}T18:00:00Z`
    EVENTS.push({
      source_id: 'fed_calendar', origin: 'synthetic', available_at: `${addDays(d, -180)}T12:00:00Z`,
      availability_inferred: false, ingested_at: null,
      event_id: `evt-fomc-${d}`, event_class: 'scheduled', subtype: 'fomc_meeting',
      title: `FOMC decision ${d.slice(0, 7)}`, status: 'occurred', scope: 'market',
      scheduled_at: at, occurred_at: at, published_at: at,
      affected_security_ids: [...BANKS], source_ids: [`synthetic://fed/fomc/${d}`],
      expected_outcome: null, actual_outcome: outcome, surprise: bps === 0 ? 0 : bps / 100,
      revision: 0, canonical_event_id: null,
    })
  }

  const extra: Array<{ id: string; cls: EventClass; subtype: string; title: string; scope: EventScope; at: string; known: string; secs: string[]; expected?: string; actual?: string }> = [
    { id: 'evt-pandemic-2020-03-09', cls: 'unexpected', subtype: 'market_shock', title: 'Pandemic market selloff', scope: 'market', at: '2020-03-09T14:30:00Z', known: '2020-03-09T14:30:00Z', secs: [...BANKS], actual: 'Broad market fell sharply' },
    { id: 'evt-svb-2023-03-10', cls: 'unexpected', subtype: 'bank_failure', title: 'Regional bank failure, sector stress', scope: 'sector', at: '2023-03-10T16:00:00Z', known: '2023-03-10T16:00:00Z', secs: [...BANKS], actual: 'Deposit flight at regional lenders' },
    { id: 'evt-tariff-2025-04-03', cls: 'unexpected', subtype: 'policy_shock', title: 'Tariff announcement, market selloff', scope: 'market', at: '2025-04-03T13:30:00Z', known: '2025-04-03T13:30:00Z', secs: [...BANKS], actual: 'Broad risk-off move' },
    { id: 'evt-stress-test-2025-06-27', cls: 'anticipated', subtype: 'regulation', title: 'Stress test results and capital plans', scope: 'sector', at: '2025-06-27T20:30:00Z', known: '2025-05-01T12:00:00Z', secs: [...BANKS], expected: 'Lower capital buffers likely', actual: 'Buffers lowered for most large banks' },
    { id: 'evt-capital-rule-2026', cls: 'anticipated', subtype: 'regulation', title: 'Possible revision to bank capital rules', scope: 'sector', at: '2026-01-15T15:00:00Z', known: '2025-09-10T12:00:00Z', secs: [...BANKS], expected: 'Capital requirement may ease' },
    { id: 'evt-rate-cut-2025-12', cls: 'anticipated', subtype: 'rate_change', title: 'Possible rate cut at December FOMC', scope: 'market', at: '2025-12-10T19:00:00Z', known: '2025-10-30T19:00:00Z', secs: [...BANKS], expected: 'Market-implied odds near even for a 25 bps cut' },
    { id: 'evt-jpm-litigation-2024-05', cls: 'unexpected', subtype: 'filing_8k', title: 'JPM 8-K: legal settlement disclosed', scope: 'firm', at: '2024-05-21T20:10:00Z', known: '2024-05-21T20:10:00Z', secs: ['JPM'], actual: 'Settlement within prior reserves' },
  ]
  for (const e of extra) {
    EVENTS.push({
      source_id: e.subtype === 'filing_8k' ? 'edgar' : 'news_fixture', origin: 'synthetic', available_at: e.known,
      availability_inferred: false, ingested_at: null,
      event_id: e.id, event_class: e.cls, subtype: e.subtype, title: e.title, status: 'occurred', scope: e.scope,
      scheduled_at: e.cls === 'unexpected' ? null : e.at, occurred_at: e.at, published_at: e.known,
      affected_security_ids: e.secs, source_ids: [`synthetic://${e.subtype}/${e.id}`],
      expected_outcome: e.expected ?? null, actual_outcome: e.actual ?? null, surprise: null,
      revision: 0, canonical_event_id: null,
    })
  }
  // A duplicate news record pointing at the canonical event (EVT-04 dedupe demo).
  EVENTS.push({
    source_id: 'news_fixture', origin: 'synthetic', available_at: '2023-03-10T17:30:00Z', availability_inferred: false,
    ingested_at: null, event_id: 'evt-svb-2023-03-10-dup', event_class: 'unexpected', subtype: 'bank_failure',
    title: 'Regional bank failure, sector stress (repeat report)', status: 'revised', scope: 'sector',
    scheduled_at: null, occurred_at: '2023-03-10T16:00:00Z', published_at: '2023-03-10T17:30:00Z',
    affected_security_ids: [...BANKS], source_ids: ['synthetic://news/repeat'], expected_outcome: null,
    actual_outcome: 'Same story from a second outlet', surprise: null, revision: 1, canonical_event_id: 'evt-svb-2023-03-10',
  })

  // Derived price-shock events: days a bank moved more than 4.5% (computed from the synthetic prices).
  for (const id of BANKS) {
    let last = -99
    RETURNS[id].forEach((r, i) => {
      if (Math.abs(r) < 0.045 || i - last < 6) return
      last = i
      const d = DAYS[i]
      EVENTS.push({
        source_id: 'forwardstate', origin: 'derived', available_at: `${d}T21:00:00Z`, availability_inferred: false,
        ingested_at: null, event_id: `evt-shock-${id}-${d}`, event_class: 'unexpected', subtype: 'price_shock',
        title: `${id} ${r > 0 ? 'jumped' : 'fell'} ${(Math.abs(r) * 100).toFixed(1)}% in one day`,
        status: 'occurred', scope: 'firm', scheduled_at: null, occurred_at: `${d}T21:00:00Z`, published_at: `${d}T21:00:00Z`,
        affected_security_ids: [id], source_ids: [], expected_outcome: null,
        actual_outcome: `Close-to-close return ${(r * 100).toFixed(1)}%`, surprise: null, revision: 0, canonical_event_id: null,
      })
    })
  }
  EVENTS.sort((a, b) => eventTime(a).localeCompare(eventTime(b)))
})()

export function eventTime(e: Event): string {
  return e.occurred_at ?? e.scheduled_at ?? e.published_at ?? e.available_at
}

/** Point-in-time view of an event: an event in the future of `asOfIso` is upcoming, with no outcome yet. */
export function eventAsOf(e: MockEvent, asOfIso: string): MockEvent | null {
  if (e.available_at > asOfIso) return null
  const t = e.occurred_at ?? e.scheduled_at
  if (t && t > asOfIso) {
    return { ...e, status: 'upcoming', occurred_at: null, actual_outcome: null, surprise: null }
  }
  return e
}

// ---------------------------------------------------------------- analysts

export const ANALYSTS: AnalystObservation[] = []
;(() => {
  const rand = mulberry32(77)
  const firms = ['Research desk A (synthetic)', 'Research desk B (synthetic)', 'Research desk C (synthetic)', 'Independent analyst D (synthetic)']
  const ratings = ['Underweight', 'Neutral', 'Overweight']
  for (const id of BANKS) {
    let rating = 1
    let target: number | null = null
    let prevId: string | null = null
    for (let k = 0; k < 10; k++) {
      const i = DAYS.length - 1 - Math.floor((9 - k) * 70 + rand() * 30) - 5
      const d = DAYS[i]
      const px = CLOSES[id][i]
      const roll = rand()
      const from = ratings[rating]
      let action: AnalystObservation['action'] = 'maintain'
      if (k === 0) action = 'initiate'
      else if (roll < 0.2 && rating < 2) { rating++; action = 'upgrade' }
      else if (roll < 0.35 && rating > 0) { rating--; action = 'downgrade' }
      else if (roll < 0.75) action = 'target_change'
      const prior = target
      target = Math.round(px * (1 + (rating - 0.6) * 0.12 + rand() * 0.06) * 100) / 100
      const obsId = `an-${id}-${k}`
      ANALYSTS.push({
        source_id: 'analyst_fixture', origin: 'synthetic', available_at: `${d}T12:30:00Z`, availability_inferred: false,
        ingested_at: null, observation_id: obsId, analyst_source: firms[k % firms.length], security_id: id, action,
        from_rating: k === 0 ? null : from, to_rating: ratings[rating], target_price: target, prior_target_price: prior,
        horizon_months: 12,
        assumptions: ['Net interest income holds near current run-rate', 'Credit costs normalise gradually', 'Capital return stays steady', 'Fee income recovers with markets'][k % 4],
        issued_at: `${d}T12:00:00Z`, revised_from: prevId, confidence: null,
      })
      prevId = obsId
    }
  }
})()

// ---------------------------------------------------------------- sources

export const SOURCES: SourceStatus[] = [
  { source_id: 'yahoo', name: 'Prices (synthetic stand-in for Yahoo)', health: 'fresh', last_fetched_at: '2025-11-22T02:10:00Z', latest_record_date: LATEST, record_count: DAYS.length * 7, message: 'Synthetic random-walk prices for the offline demo.' },
  { source_id: 'fred', name: 'Macro rates (synthetic stand-in for FRED)', health: 'fresh', last_fetched_at: '2025-11-22T02:12:00Z', latest_record_date: '2025-11-20', record_count: MACRO.length, message: null },
  { source_id: 'fed_calendar', name: 'FOMC calendar', health: 'stale', last_fetched_at: '2025-10-01T09:00:00Z', latest_record_date: '2025-10-30', record_count: FOMC_DATES.length, message: 'Not refreshed for 52 days. Upcoming meeting dates may have moved.' },
  { source_id: 'edgar', name: 'Company filings (EDGAR)', health: 'disabled', last_fetched_at: null, latest_record_date: null, record_count: 0, message: 'Disabled: no User-Agent is set. Earnings data comes from fixtures.' },
  { source_id: 'analyst_fixture', name: 'Analyst views (fixture)', health: 'fresh', last_fetched_at: '2025-11-22T02:00:00Z', latest_record_date: '2025-11-14', record_count: ANALYSTS.length, message: 'Invented analyst records for the demo.' },
]
