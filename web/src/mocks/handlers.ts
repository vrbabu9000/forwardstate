import { http, HttpResponse, delay } from 'msw'
import type {
  AlertsRequest,
  ForecastRequest,
  Meta,
  PeerComparison,
  PeerSeries,
  PortfolioRequest,
  PriceSeries,
  ReplayRequest,
  Settings,
  TransitionRequest,
} from '../api/types'
import {
  ANALYSTS,
  BANKS,
  CLOSES,
  DAYS,
  DECISION_BOUNDARY,
  EVENTS,
  FUNDAMENTALS,
  MACRO,
  MOCK_VERSION,
  SECURITIES,
  SOURCES,
  dayIndexAtOrBefore,
  eventAsOf,
  rawClose,
} from './data'
import {
  asOfIndex,
  computeForecast,
  db,
  evaluatePortfolio,
  impactFor,
  reproduce,
  resolveAsOf,
  runAlerts,
  runReplay,
} from './engine'

const A = '*/api'
const LATENCY = import.meta.env.MODE === 'test' ? 0 : 120

function notFound(what: string, id: string) {
  return HttpResponse.json({ detail: { code: 'not_found', message: `Unknown ${what}: ${id}`, field: null } }, { status: 404 })
}
function invalid(message: string, field: string | null = null) {
  return HttpResponse.json({ detail: { code: 'invalid', message, field } }, { status: 422 })
}

function range(url: URL, asOfIso: string, defaultYears = 3) {
  const end = Math.min(asOfIndex(asOfIso), url.searchParams.get('end') ? dayIndexAtOrBefore(url.searchParams.get('end') as string) : Infinity)
  const startParam = url.searchParams.get('start')
  const start = startParam ? Math.max(0, dayIndexAtOrBefore(startParam) + (DAYS[dayIndexAtOrBefore(startParam)] < startParam ? 1 : 0)) : Math.max(0, end - defaultYears * 252)
  return { start, end }
}

export const handlers = [
  http.get(`${A}/health`, () => HttpResponse.json({ status: 'ok' })),

  http.get(`${A}/meta`, () => {
    const meta: Meta = { app: 'ForwardState', version: MOCK_VERSION, contract_version: '1.0.0', mode: 'replay', data_origin: 'synthetic', sector: 'financials', disclaimer: DECISION_BOUNDARY }
    return HttpResponse.json(meta)
  }),

  http.get(`${A}/sources`, () => HttpResponse.json(SOURCES)),

  // The MVP has one sector module; its universe includes the market benchmark and cash.
  http.get(`${A}/securities`, () => HttpResponse.json(SECURITIES)),

  http.get(`${A}/prices/:id`, async ({ params, request }) => {
    await delay(LATENCY)
    const id = String(params.id)
    if (!CLOSES[id]) return notFound('security', id)
    const url = new URL(request.url)
    const asOfIso = resolveAsOf(url.searchParams.get('as_of'))
    const { start, end } = range(url, asOfIso)
    const body: PriceSeries = {
      security_id: id, as_of: asOfIso, origin: 'synthetic',
      points: DAYS.slice(start, end + 1).map((d, k) => ({ date: d, close: CLOSES[id][start + k], raw_close: rawClose(id, start + k), volume: Math.round(8e6 + 4e6 * Math.abs(Math.sin(start + k))) })),
    }
    return HttpResponse.json(body)
  }),

  http.get(`${A}/peers/:id`, async ({ params, request }) => {
    await delay(LATENCY)
    const id = String(params.id)
    if (!CLOSES[id]) return notFound('security', id)
    const url = new URL(request.url)
    const asOfIso = resolveAsOf(url.searchParams.get('as_of'))
    const { start, end } = range(url, asOfIso, 1)
    const ids = [id, ...BANKS.filter((b) => b !== id), 'XLF']
    const series: PeerSeries[] = ids.map((s) => {
      const c = CLOSES[s].slice(start, end + 1)
      const rets = c.slice(1).map((x, i) => x / c[i] - 1)
      const mu = rets.reduce((a, b) => a + b, 0) / rets.length
      const sd = Math.sqrt(rets.reduce((a, b) => a + (b - mu) ** 2, 0) / (rets.length - 1))
      let peak = c[0]
      let mdd = 0
      c.forEach((x) => { peak = Math.max(peak, x); mdd = Math.max(mdd, 1 - x / peak) })
      return {
        security_id: s,
        points: c.map((x, k) => ({ date: DAYS[start + k], value: Math.round((x / c[0]) * 10000) / 100 })),
        total_return: Math.round((c[c.length - 1] / c[0] - 1) * 1e5) / 1e5,
        volatility_annual: Math.round(sd * Math.sqrt(252) * 1e5) / 1e5,
        max_drawdown: Math.round(mdd * 1e5) / 1e5,
      }
    })
    const body: PeerComparison = { focal_id: id, base_date: DAYS[start], as_of: asOfIso, series }
    return HttpResponse.json(body)
  }),

  http.get(`${A}/events`, async ({ request }) => {
    await delay(LATENCY)
    const url = new URL(request.url)
    const asOfIso = resolveAsOf(url.searchParams.get('as_of'))
    const sec = url.searchParams.get('security_id')
    const cls = url.searchParams.get('event_class')
    const start = url.searchParams.get('start')
    const end = url.searchParams.get('end')
    const out = EVENTS.map((e) => eventAsOf(e, asOfIso)).filter((e): e is NonNullable<typeof e> => {
      if (!e) return false
      if (sec && !e.affected_security_ids.includes(sec)) return false
      if (cls && e.event_class !== cls) return false
      const t = (e.occurred_at ?? e.scheduled_at ?? e.available_at).slice(0, 10)
      if (start && t < start) return false
      if (end && t > end) return false
      return true
    })
    return HttpResponse.json(out)
  }),

  http.get(`${A}/events/:id/impact`, async ({ params, request }) => {
    await delay(LATENCY)
    const asOfIso = resolveAsOf(new URL(request.url).searchParams.get('as_of'))
    const out = impactFor(String(params.id), asOfIso)
    return out ? HttpResponse.json(out) : notFound('event', String(params.id))
  }),

  http.get(`${A}/analysts`, ({ request }) => {
    const url = new URL(request.url)
    const asOfIso = resolveAsOf(url.searchParams.get('as_of'))
    const sec = url.searchParams.get('security_id')
    return HttpResponse.json(ANALYSTS.filter((a) => a.available_at <= asOfIso && (!sec || a.security_id === sec)))
  }),

  http.get(`${A}/fundamentals`, ({ request }) => {
    const url = new URL(request.url)
    const asOfIso = resolveAsOf(url.searchParams.get('as_of'))
    const sec = url.searchParams.get('security_id')
    const metrics = url.searchParams.getAll('metric_id')
    return HttpResponse.json(FUNDAMENTALS.filter((o) => o.available_at <= asOfIso && (!sec || o.security_id === sec) && (!metrics.length || metrics.includes(o.metric_id))))
  }),

  http.get(`${A}/macro`, ({ request }) => {
    const url = new URL(request.url)
    const asOfIso = resolveAsOf(url.searchParams.get('as_of'))
    const metrics = url.searchParams.getAll('metric_id')
    const start = url.searchParams.get('start')
    return HttpResponse.json(MACRO.filter((o) => o.available_at <= asOfIso && (!metrics.length || metrics.includes(o.metric_id)) && (!start || o.period_end >= start)))
  }),

  http.post(`${A}/forecast`, async ({ request }) => {
    await delay(LATENCY * 2)
    const req = (await request.json()) as ForecastRequest
    if (!req.security_ids?.length) return invalid('Pick at least one security.', 'security_ids')
    const unknown = req.security_ids.find((s) => !CLOSES[s] && s !== 'CASH')
    if (unknown) return notFound('security', unknown)
    const v = req.assumptions?.volatility_multiplier
    if (v !== undefined && v <= 0) return invalid('Volatility multiplier must be above 0.', 'assumptions.volatility_multiplier')
    const w = req.assumptions?.analyst_weight
    if (w !== undefined && (w < 0 || w > 1)) return invalid('Analyst weight must be between 0 and 1.', 'assumptions.analyst_weight')
    return HttpResponse.json(computeForecast(req))
  }),

  http.post(`${A}/portfolio/evaluate`, async ({ request }) => {
    await delay(LATENCY * 2)
    const req = (await request.json()) as PortfolioRequest
    if (!(req.portfolio?.total_value > 0)) return invalid('Total value must be above 0.', 'portfolio.total_value')
    return HttpResponse.json(evaluatePortfolio(req, false))
  }),

  http.post(`${A}/portfolio/optimize`, async ({ request }) => {
    await delay(LATENCY * 3)
    const req = (await request.json()) as PortfolioRequest
    if (!(req.portfolio?.total_value > 0)) return invalid('Total value must be above 0.', 'portfolio.total_value')
    return HttpResponse.json(evaluatePortfolio(req, true))
  }),

  http.get(`${A}/alerts/rules`, () => HttpResponse.json(db.settings.alert_rules)),

  http.post(`${A}/alerts/evaluate`, async ({ request }) => {
    const req = (await request.json()) as AlertsRequest
    const { alerts } = runAlerts(req.portfolio, req.assumptions ?? {}, resolveAsOf(req.as_of ?? null), req.rule_ids ?? null)
    return HttpResponse.json(alerts)
  }),

  http.get(`${A}/alerts`, ({ request }) => {
    const status = new URL(request.url).searchParams.get('status')
    return HttpResponse.json(db.alerts.filter((a) => !status || a.status === status))
  }),

  http.post(`${A}/alerts/:id/transition`, async ({ params, request }) => {
    const alert = db.alerts.find((a) => a.alert_id === params.id)
    if (!alert) return notFound('alert', String(params.id))
    const req = (await request.json()) as TransitionRequest
    const allowed: Record<string, string[]> = { new: ['acknowledged', 'resolved'], acknowledged: ['resolved'], resolved: [], superseded: [] }
    if (!allowed[alert.status ?? 'new']?.includes(req.to_status)) {
      return invalid(`Cannot move an alert from ${alert.status} to ${req.to_status}.`, 'to_status')
    }
    alert.status = req.to_status
    return HttpResponse.json(alert)
  }),

  http.post(`${A}/replay`, async ({ request }) => {
    await delay(LATENCY * 4)
    const req = (await request.json()) as ReplayRequest
    if (!req.start || !req.end || req.start > req.end) return invalid('Start date must be on or before the end date.', 'start')
    if (dayIndexAtOrBefore(req.end) - dayIndexAtOrBefore(req.start) > 400) return invalid('Replay up to about 18 months at a time.', 'end')
    if (req.step_trading_days != null && (req.step_trading_days < 1 || req.step_trading_days > 20)) return invalid('Step must be 1 to 20 days.', 'step_trading_days')
    return HttpResponse.json(runReplay(req))
  }),

  http.get(`${A}/settings`, () => HttpResponse.json(db.settings)),

  http.put(`${A}/settings`, async ({ request }) => {
    const s = (await request.json()) as Settings
    for (const [h, n] of Object.entries(s.horizon_days ?? {})) {
      if (!Number.isInteger(n) || n < 1 || n > 1260) return invalid(`Horizon ${h} must be a whole number of days from 1 to 1260.`, `horizon_days.${h}`)
    }
    db.settings = s
    return HttpResponse.json(db.settings)
  }),

  http.get(`${A}/runs`, ({ request }) => {
    const url = new URL(request.url)
    const kind = url.searchParams.get('kind')
    const limit = Number(url.searchParams.get('limit') ?? 50)
    return HttpResponse.json(db.runs.filter((r) => !kind || r.kind === kind).slice(0, limit))
  }),

  http.get(`${A}/runs/:id`, ({ params }) => {
    const r = db.runs.find((x) => x.run_id === params.id)
    return r ? HttpResponse.json(r) : notFound('run', String(params.id))
  }),

  http.post(`${A}/runs/:id/reproduce`, async ({ params }) => {
    await delay(LATENCY * 2)
    const r = reproduce(String(params.id))
    return r ? HttpResponse.json(r) : notFound('run', String(params.id))
  }),
]
