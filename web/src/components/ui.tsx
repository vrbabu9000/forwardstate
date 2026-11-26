import type { ReactNode } from 'react'
import type { AlertSeverity, Confidence, DataOrigin } from '../api/types'
import { ApiError } from '../api/client'
import { useApp } from '../state/app'

const ORIGIN_TEXT: Record<DataOrigin, string> = { real: 'Real', derived: 'Derived', synthetic: 'Synthetic' }
const ORIGIN_HELP: Record<DataOrigin, string> = {
  real: 'Fetched from a real source.',
  derived: 'Computed by ForwardState from source data.',
  synthetic: 'Generated for the demo. Not real market data.',
}

export function OriginBadge({ origin, className = '' }: { origin: DataOrigin | null | undefined; className?: string }) {
  const o: DataOrigin = origin ?? 'synthetic'
  const style =
    o === 'real'
      ? 'border-ok text-ok'
      : o === 'derived'
        ? 'border-ev-derived text-ev-derived'
        : 'border-warn text-warn bg-warn-soft'
  return (
    <span
      title={ORIGIN_HELP[o]}
      className={`inline-flex items-center gap-1 rounded-sm border px-1.5 text-[11px] leading-[18px] font-semibold ${style} ${className}`}
    >
      <span aria-hidden className={`inline-block h-1.5 w-1.5 rounded-full ${o === 'real' ? 'bg-ok' : o === 'derived' ? 'bg-ev-derived' : 'bg-warn'}`} />
      {ORIGIN_TEXT[o]}
      <span className="sr-only"> data: {ORIGIN_HELP[o]}</span>
    </span>
  )
}

const CONF_STYLE: Record<Confidence, string> = {
  high: 'text-ok border-ok',
  medium: 'text-accent border-accent',
  low: 'text-warn border-warn bg-warn-soft',
  unavailable: 'text-danger border-danger bg-danger-soft',
}

export function ConfidenceBadge({ value, prefix = 'Confidence' }: { value: Confidence; prefix?: string }) {
  return (
    <span className={`inline-flex items-center rounded-sm border px-1.5 text-[11px] leading-[18px] font-semibold ${CONF_STYLE[value]}`}>
      {prefix ? `${prefix}: ` : ''}
      {value}
    </span>
  )
}

const SEV_STYLE: Record<AlertSeverity, string> = {
  info: 'bg-accent-soft text-accent',
  warning: 'bg-warn-soft text-warn',
  high: 'bg-danger-soft text-danger',
  critical: 'bg-danger text-surface',
}

export function SeverityBadge({ value }: { value: AlertSeverity }) {
  return <span className={`inline-flex rounded-sm px-1.5 text-[11px] leading-[18px] font-bold ${SEV_STYLE[value]}`}>{value}</span>
}

export function SimulatedTag() {
  return (
    <span className="text-[11px] font-semibold text-warn" title="From a simple simulation. Not calibrated against outcomes.">
      simulated, uncalibrated
    </span>
  )
}

export function Panel({
  title,
  aside,
  children,
  className = '',
  id,
  description,
}: {
  title: ReactNode
  aside?: ReactNode
  children: ReactNode
  className?: string
  id?: string
  description?: ReactNode
}) {
  const hid = id ? `${id}-title` : undefined
  return (
    <section className={`panel min-w-0 ${className}`} aria-labelledby={hid}>
      <header className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-line px-4 py-2.5">
        <div className="min-w-0">
          <h2 id={hid} className="text-[15px] font-semibold">
            {title}
          </h2>
          {description ? <p className="text-xs text-muted">{description}</p> : null}
        </div>
        {aside ? <div className="flex flex-wrap items-center gap-2">{aside}</div> : null}
      </header>
      <div className="p-4">{children}</div>
    </section>
  )
}

/** Shown instead of a number whenever data is unavailable or weak. Never blank. */
export function StatusNotice({ status, reason }: { status: Confidence; reason?: string | null }) {
  if (status === 'high' || status === 'medium') return null
  const unavailable = status === 'unavailable'
  return (
    <div
      role="status"
      className={`flex gap-2 rounded border px-3 py-2 text-sm ${unavailable ? 'border-danger bg-danger-soft' : 'border-warn bg-warn-soft'}`}
    >
      <strong className={unavailable ? 'text-danger' : 'text-warn'}>{unavailable ? 'Forecast unavailable.' : 'Low confidence.'}</strong>
      <span className="text-ink-2">{reason ?? (unavailable ? 'Not enough data to give a number.' : 'Treat this range as rough.')}</span>
    </div>
  )
}

export function OptionsNotice({ className = '' }: { className?: string }) {
  return (
    <p className={`text-xs font-semibold text-ink-2 ${className}`}>
      Options to consider — not instructions. You decide whether and how to act.
    </p>
  )
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null
  const msg = error instanceof ApiError ? error.message : error instanceof Error ? error.message : 'Something went wrong.'
  const hint =
    error instanceof ApiError && error.status === 503
      ? ' The server has not loaded data yet. Try again shortly.'
      : error instanceof TypeError
        ? ' The API could not be reached. Check that the backend is running.'
        : ''
  return (
    <div role="alert" className="rounded border border-danger bg-danger-soft px-3 py-2 text-sm text-ink">
      {msg}
      {hint}
    </div>
  )
}

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="py-6 text-center text-sm text-muted">
      {label}…
    </div>
  )
}

export function ProvenanceButton({ runId, label = 'How this was computed' }: { runId: string | null | undefined; label?: string }) {
  const { openProvenance } = useApp()
  if (!runId) return null
  return (
    <button type="button" className="btn btn-quiet text-xs" onClick={() => openProvenance(runId)}>
      {label}
      <span className="sr-only"> (run {runId})</span>
    </button>
  )
}

export function Dot({ color }: { color: string }) {
  return <span aria-hidden className="inline-block h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: color }} />
}

export function Label({ htmlFor, children, hint }: { htmlFor: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="mb-1 block text-xs font-semibold text-ink-2">
      {children}
      {hint ? <span className="ml-1 font-normal text-muted">{hint}</span> : null}
    </label>
  )
}

export function FieldError({ id, children }: { id: string; children: ReactNode }) {
  if (!children) return null
  return (
    <p id={id} className="mt-1 text-xs font-semibold text-danger">
      {children}
    </p>
  )
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: 'good' | 'bad' }) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-muted">{label}</div>
      <div className={`text-lg font-semibold tabular-nums ${tone === 'good' ? 'text-opt' : tone === 'bad' ? 'text-pes' : ''}`}>{value}</div>
      {hint ? <div className="text-[11px] text-muted">{hint}</div> : null}
    </div>
  )
}
