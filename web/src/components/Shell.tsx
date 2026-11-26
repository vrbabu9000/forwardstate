import { useEffect, useId, useState } from 'react'
import { NavLink, Outlet, useLocation, useMatch, useNavigate } from 'react-router'
import { useMeta, useSecurities, useSources } from '../api/hooks'
import { useApp } from '../state/app'
import { useTheme } from '../state/theme'
import { day } from '../lib/format'
import { OriginBadge } from './ui'
import { ProvenanceDrawer } from './ProvenanceDrawer'

const NAV = [
  { to: '/research/JPM', match: '/research', label: 'Stock research', hint: 'Prices, events, scenarios' },
  { to: '/portfolio', match: '/portfolio', label: 'Portfolio', hint: 'Risk and candidates' },
  { to: '/alerts', match: '/alerts', label: 'Events & alerts', hint: 'Timeline, inbox, replay' },
  { to: '/settings', match: '/settings', label: 'Settings', hint: 'Rules, defaults, sources' },
]

function Mark() {
  return (
    <svg aria-hidden viewBox="0 0 32 32" className="h-7 w-7 shrink-0">
      <rect width="32" height="32" rx="6" fill="var(--accent)" />
      <path d="M6 22 L13 15 L18 19 L26 9" stroke="var(--accent-ink)" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function SecuritySelect() {
  const { data } = useSecurities()
  const navigate = useNavigate()
  const m = useMatch('/research/:securityId')
  const id = useId()
  const banks = (data ?? []).filter((s) => s.role === 'focal' || s.role === 'peer')
  const current = m?.params.securityId ?? 'JPM'
  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="sr-only text-xs font-semibold text-muted sm:not-sr-only">
        Security
      </label>
      <select id={id} className="field w-[9.5rem] sm:w-56" value={current} onChange={(e) => navigate(`/research/${e.target.value}`)}>
        {banks.length === 0 ? <option value={current}>{current}</option> : null}
        {banks.map((s) => (
          <option key={s.security_id} value={s.security_id}>
            {s.ticker} · {s.name}
          </option>
        ))}
      </select>
    </div>
  )
}

function AsOfPicker() {
  const { asOf, setAsOf } = useApp()
  const { data: sources } = useSources()
  const id = useId()
  const latest = sources?.find((s) => s.source_id === 'yahoo')?.latest_record_date ?? undefined
  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="text-xs font-semibold text-muted whitespace-nowrap">
        Replay as of
      </label>
      <input
        id={id}
        type="date"
        className="field w-[9.5rem]"
        value={asOf ?? latest ?? ''}
        max={latest}
        min="2019-01-02"
        onChange={(e) => setAsOf(e.target.value && e.target.value !== latest ? e.target.value : null)}
      />
      {asOf ? (
        <button type="button" className="btn btn-quiet text-xs" onClick={() => setAsOf(null)}>
          Latest
        </button>
      ) : null}
    </div>
  )
}

function ModeTape() {
  const { data: meta } = useMeta()
  const { data: sources } = useSources()
  const { asOf } = useApp()
  const stale = (sources ?? []).filter((s) => s.health !== 'fresh')
  return (
    <div className="tape border-b border-line" role="note" aria-label="Data mode">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-1.5 text-xs font-semibold">
        <span>Replay mode — historical data, not live</span>
        {meta?.data_origin === 'synthetic' ? <span>All data on screen is synthetic (generated for the demo)</span> : null}
        {asOf ? <span>Showing what was known on {day(asOf)}</span> : null}
        {stale.length ? (
          <NavLink to="/settings#sources" className="underline underline-offset-2">
            {stale.length} source{stale.length > 1 ? 's' : ''} not fresh
          </NavLink>
        ) : null}
      </div>
    </div>
  )
}

export function Shell() {
  const { data: meta } = useMeta()
  const { openProvenance } = useApp()
  const { theme, toggle } = useTheme()
  const [navOpen, setNavOpen] = useState(false)
  const loc = useLocation()
  useEffect(() => setNavOpen(false), [loc.pathname])

  return (
    <div className="min-h-dvh">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 btn">
        Skip to content
      </a>
      <ModeTape />
      <div className="flex">
        {/* nav */}
        <nav
          aria-label="Views"
          className={`${navOpen ? 'fixed inset-0 z-40 flex' : 'hidden'} lg:sticky lg:top-0 lg:flex lg:h-dvh lg:w-60 shrink-0 flex-col border-r border-line bg-surface`}
        >
          <div className="flex items-center gap-2 px-4 py-3.5">
            <Mark />
            <div className="min-w-0">
              <div className="serif text-[19px] leading-none font-semibold">ForwardState</div>
              <div className="text-[11px] text-muted">Bank scenarios and risk</div>
            </div>
            <button type="button" className="btn btn-quiet ml-auto lg:hidden" onClick={() => setNavOpen(false)}>
              Close
            </button>
          </div>
          <ul className="flex flex-col gap-0.5 px-2 py-2">
            {NAV.map((n) => (
              <li key={n.to}>
                <NavLink
                  to={n.to}
                  className={() => {
                    const active = loc.pathname.startsWith(n.match)
                    return `block rounded px-3 py-2 ${active ? 'bg-accent-soft text-ink' : 'text-ink-2 hover:bg-surface-2'}`
                  }}
                  aria-current={loc.pathname.startsWith(n.match) ? 'page' : undefined}
                >
                  <span className="block text-sm font-semibold">{n.label}</span>
                  <span className="block text-[11px] text-muted">{n.hint}</span>
                </NavLink>
              </li>
            ))}
          </ul>
          <div className="mt-auto space-y-2 border-t border-line px-4 py-3 text-[11px] text-muted">
            <div className="flex items-center gap-2">
              Data <OriginBadge origin={meta?.data_origin} />
            </div>
            <div>
              App {meta?.version ?? '…'} · contract {meta?.contract_version ?? '…'}
            </div>
          </div>
        </nav>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="z-30 border-b border-line bg-surface/95 backdrop-blur lg:sticky lg:top-0">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2">
              <button type="button" className="btn lg:hidden" aria-expanded={navOpen} onClick={() => setNavOpen(true)}>
                Menu
              </button>
              <SecuritySelect />
              <AsOfPicker />
              <div className="ml-auto flex items-center gap-1">
                <button type="button" className="btn" onClick={() => openProvenance(null)}>
                  Runs
                </button>
                <button type="button" className="btn" onClick={toggle} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}>
                  {theme === 'dark' ? 'Light' : 'Dark'}
                </button>
              </div>
            </div>
          </header>

          <main id="main" className="min-w-0 flex-1 px-3 py-4 sm:px-5 lg:px-6">
            <Outlet />
          </main>

          <footer className="border-t border-line bg-surface px-4 py-3 text-xs text-ink-2" data-boundary>
            <p className="max-w-[80ch]">
              <strong className="text-ink">Decision boundary. </strong>
              {meta?.disclaimer ?? 'ForwardState is decision support only. You decide whether and how to act.'}
            </p>
          </footer>
        </div>
      </div>
      <ProvenanceDrawer />
    </div>
  )
}
