import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiSend } from './client'
import type {
  Alert,
  AlertRule,
  AlertStatus,
  AnalystObservation,
  Event,
  EventClass,
  ForecastRequest,
  ForecastRun,
  ImpactEstimate,
  Meta,
  Observation,
  PeerComparison,
  PortfolioEvaluation,
  PortfolioRequest,
  PriceSeries,
  ReplayRequest,
  ReplayResult,
  ReproduceResult,
  RunKind,
  RunRecord,
  Security,
  Settings,
  SourceStatus,
} from './types'

const STATIC = { staleTime: 5 * 60_000 }

export const useMeta = () => useQuery({ queryKey: ['meta'], queryFn: () => apiGet<Meta>('/meta'), ...STATIC })

export const useSources = () =>
  useQuery({ queryKey: ['sources'], queryFn: () => apiGet<SourceStatus[]>('/sources'), staleTime: 60_000 })

export const useSecurities = () =>
  useQuery({
    queryKey: ['securities'],
    queryFn: () => apiGet<Security[]>('/securities', { sector: 'financials' }),
    ...STATIC,
  })

export const usePrices = (securityId: string, asOf: string | null, start?: string) =>
  useQuery({
    queryKey: ['prices', securityId, asOf, start],
    queryFn: () => apiGet<PriceSeries>(`/prices/${encodeURIComponent(securityId)}`, { as_of: asOf, start }),
    placeholderData: keepPreviousData,
  })

export const usePeers = (securityId: string, asOf: string | null, start?: string) =>
  useQuery({
    queryKey: ['peers', securityId, asOf, start],
    queryFn: () => apiGet<PeerComparison>(`/peers/${encodeURIComponent(securityId)}`, { as_of: asOf, start }),
    placeholderData: keepPreviousData,
  })

export interface EventFilter {
  security_id?: string
  event_class?: EventClass | ''
  start?: string
  end?: string
}

export const useEvents = (filter: EventFilter, asOf: string | null) =>
  useQuery({
    queryKey: ['events', filter, asOf],
    queryFn: () => apiGet<Event[]>('/events', { ...filter, as_of: asOf }),
    placeholderData: keepPreviousData,
  })

export const useImpact = (eventId: string | null, asOf: string | null) =>
  useQuery({
    queryKey: ['impact', eventId, asOf],
    queryFn: () => apiGet<ImpactEstimate[]>(`/events/${encodeURIComponent(eventId ?? '')}/impact`, { as_of: asOf }),
    enabled: !!eventId,
  })

export const useAnalysts = (securityId: string, asOf: string | null) =>
  useQuery({
    queryKey: ['analysts', securityId, asOf],
    queryFn: () => apiGet<AnalystObservation[]>('/analysts', { security_id: securityId, as_of: asOf }),
  })

export const useFundamentals = (securityId: string, asOf: string | null) =>
  useQuery({
    queryKey: ['fundamentals', securityId, asOf],
    queryFn: () =>
      apiGet<Observation[]>('/fundamentals', {
        security_id: securityId,
        metric_id: ['eps_actual', 'eps_estimate'],
        as_of: asOf,
      }),
  })

export const MACRO_METRICS = ['DFF', 'DGS2', 'DGS10'] as const

export const useMacro = (asOf: string | null, start: string) =>
  useQuery({
    queryKey: ['macro', asOf, start],
    queryFn: () => apiGet<Observation[]>('/macro', { metric_id: [...MACRO_METRICS], start, as_of: asOf }),
  })

/** Forecasts are a POST, but they are a pure function of the request, so they are cached by it. */
export const useForecast = (req: ForecastRequest | null) =>
  useQuery({
    queryKey: ['forecast', req],
    queryFn: () => apiSend<ForecastRun>('POST', '/forecast', req),
    enabled: !!req,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  })

function useRunInvalidation() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ queryKey: ['runs'] })
}

export const useEvaluatePortfolio = () => {
  const inv = useRunInvalidation()
  return useMutation({
    mutationFn: (req: PortfolioRequest) => apiSend<PortfolioEvaluation>('POST', '/portfolio/evaluate', req),
    onSuccess: inv,
  })
}

export const useOptimizePortfolio = () => {
  const inv = useRunInvalidation()
  return useMutation({
    mutationFn: (req: PortfolioRequest) => apiSend<PortfolioEvaluation>('POST', '/portfolio/optimize', req),
    onSuccess: inv,
  })
}

export const useAlertRules = () =>
  useQuery({ queryKey: ['alert-rules'], queryFn: () => apiGet<AlertRule[]>('/alerts/rules') })

export const useAlerts = (status: AlertStatus | '') =>
  useQuery({ queryKey: ['alerts', status], queryFn: () => apiGet<Alert[]>('/alerts', { status }) })

export const useTransitionAlert = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ alertId, to, note }: { alertId: string; to: AlertStatus; note?: string }) =>
      apiSend<Alert>('POST', `/alerts/${encodeURIComponent(alertId)}/transition`, { to_status: to, note: note ?? null }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['alerts'] }),
  })
}

export const useReplay = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: ReplayRequest) => apiSend<ReplayResult>('POST', '/replay', req),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['alerts'] })
      void qc.invalidateQueries({ queryKey: ['runs'] })
    },
  })
}

export const useSettings = () =>
  useQuery({ queryKey: ['settings'], queryFn: () => apiGet<Settings>('/settings'), ...STATIC })

export const useSaveSettings = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (s: Settings) => apiSend<Settings>('PUT', '/settings', s),
    onSuccess: (s) => {
      qc.setQueryData(['settings'], s)
      void qc.invalidateQueries({ queryKey: ['alert-rules'] })
    },
  })
}

export const useRuns = (kind: RunKind | '', enabled = true) =>
  useQuery({
    queryKey: ['runs', kind],
    queryFn: () => apiGet<RunRecord[]>('/runs', { kind, limit: 50 }),
    enabled,
  })

export const useRun = (runId: string | null) =>
  useQuery({
    queryKey: ['run', runId],
    queryFn: () => apiGet<RunRecord>(`/runs/${encodeURIComponent(runId ?? '')}`),
    enabled: !!runId,
  })

export const useReproduce = () =>
  useMutation({
    mutationFn: (runId: string) => apiSend<ReproduceResult>('POST', `/runs/${encodeURIComponent(runId)}/reproduce`),
  })
