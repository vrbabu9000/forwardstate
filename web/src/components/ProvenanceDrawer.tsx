import { useEffect, useId, useRef, useState } from 'react'
import { useReproduce, useRun, useRuns } from '../api/hooks'
import type { RunKind } from '../api/types'
import { useApp } from '../state/app'
import { dateTime, shortHash } from '../lib/format'
import { ErrorBox, Loading, OriginBadge } from './ui'

const KINDS: Array<RunKind | ''> = ['', 'forecast', 'portfolio', 'optimize', 'alerts', 'replay']

function Hash({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="grid grid-cols-[8.5rem_1fr] gap-2 py-1 text-xs">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-all font-semibold" title={value ?? undefined}>
        {value ?? '—'}
      </dd>
    </div>
  )
}

export function ProvenanceDrawer() {
  const { provenance, closeProvenance } = useApp()
  const [kind, setKind] = useState<RunKind | ''>('')
  const [selected, setSelected] = useState<string | null>(null)
  const runs = useRuns(kind, provenance.open)
  const run = useRun(provenance.open ? selected : null)
  const repro = useReproduce()
  const closeRef = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  const kindId = useId()

  useEffect(() => {
    if (provenance.open) {
      setSelected(provenance.runId)
      repro.reset()
      closeRef.current?.focus()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provenance.open, provenance.runId])

  useEffect(() => {
    if (!provenance.open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && closeProvenance()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [provenance.open, closeProvenance])

  if (!provenance.open) return null
  const r = run.data
  const res = repro.data && repro.data.run_id === selected ? repro.data : null

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button type="button" aria-label="Close run provenance" className="absolute inset-0 bg-black/30" onClick={closeProvenance} tabIndex={-1} />
      <aside role="dialog" aria-modal="true" aria-labelledby={titleId} className="relative flex h-full w-full max-w-[40rem] flex-col border-l border-line bg-surface shadow-xl">
        <header className="flex items-center gap-3 border-b border-line px-4 py-3">
          <div className="min-w-0">
            <h2 id={titleId} className="text-base font-semibold">
              Run provenance
            </h2>
            <p className="text-xs text-muted">Every computed result is stored with its request, data cutoff, model version and hashes.</p>
          </div>
          <button ref={closeRef} type="button" className="btn ml-auto" onClick={closeProvenance}>
            Close
          </button>
        </header>

        <div className="grid min-h-0 flex-1 grid-rows-[minmax(9rem,38%)_1fr]">
          <div className="flex min-h-0 flex-col border-b border-line">
            <div className="flex items-center gap-2 px-4 py-2">
              <label htmlFor={kindId} className="text-xs font-semibold text-muted">
                Kind
              </label>
              <select id={kindId} className="field" value={kind} onChange={(e) => setKind(e.target.value as RunKind | '')}>
                {KINDS.map((k) => (
                  <option key={k} value={k}>
                    {k || 'All runs'}
                  </option>
                ))}
              </select>
              <span className="ml-auto text-xs text-muted">{runs.data ? `${runs.data.length} runs` : ''}</span>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
              {runs.isLoading ? <Loading label="Loading runs" /> : null}
              <ErrorBox error={runs.error} />
              {runs.data?.length === 0 ? <p className="px-2 py-3 text-sm text-muted">No runs yet. Compute a forecast, portfolio or replay to create one.</p> : null}
              <ul>
                {runs.data?.map((x) => (
                  <li key={x.run_id}>
                    <button
                      type="button"
                      onClick={() => { setSelected(x.run_id); repro.reset() }}
                      aria-pressed={selected === x.run_id}
                      className={`grid w-full grid-cols-[5.5rem_1fr_auto] items-baseline gap-2 rounded px-2 py-1.5 text-left text-xs ${selected === x.run_id ? 'bg-accent-soft' : 'hover:bg-surface-2'}`}
                    >
                      <span className="font-semibold">{x.kind}</span>
                      <span className="truncate text-ink-2">{x.run_id}</span>
                      <span className="text-muted">{dateTime(x.created_at)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div className="min-h-0 overflow-y-auto px-4 py-3">
            {!selected ? <p className="text-sm text-muted">Pick a run to see where its numbers came from.</p> : null}
            {selected && run.isLoading ? <Loading label="Loading run" /> : null}
            <ErrorBox error={run.error} />
            {r ? (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-sm font-semibold">{r.run_id}</h3>
                  <OriginBadge origin={r.data_origin} />
                  <span className="text-xs text-muted">{r.kind}</span>
                </div>
                <dl className="divide-y divide-line rounded border border-line px-3">
                  <Hash label="Created" value={dateTime(r.created_at)} />
                  <Hash label="As of" value={dateTime(r.as_of)} />
                  <Hash label="Data cutoff" value={dateTime(r.data_cutoff)} />
                  <Hash label="Model version" value={r.model_version} />
                  <Hash label="Contract" value={r.contract_version} />
                  <Hash label="Config hash" value={r.config_hash} />
                  <Hash label="Input hash" value={r.input_hash} />
                  <Hash label="Output hash" value={r.output_hash} />
                </dl>

                <div className="flex flex-wrap items-center gap-3">
                  <button type="button" className="btn btn-primary" disabled={repro.isPending} onClick={() => repro.mutate(r.run_id)}>
                    {repro.isPending ? 'Reproducing…' : 'Reproduce'}
                  </button>
                  <span className="text-xs text-muted">Re-runs the stored request with the same as-of date and compares output hashes.</span>
                </div>
                <ErrorBox error={repro.error} />
                {res ? (
                  <div role="status" className={`rounded border px-3 py-2 text-sm ${res.match ? 'border-ok bg-opt-soft' : 'border-danger bg-danger-soft'}`}>
                    <strong className={res.match ? 'text-ok' : 'text-danger'}>{res.match ? 'Match.' : 'Mismatch.'}</strong>{' '}
                    Original {shortHash(res.original_output_hash)} vs reproduced {shortHash(res.reproduced_output_hash)}.
                    {res.note ? <span className="block text-xs text-ink-2">{res.note}</span> : null}
                  </div>
                ) : null}

                {r.source_status?.length ? (
                  <div>
                    <h4 className="mb-1 text-xs font-semibold text-muted">Source status at run time</h4>
                    <ul className="text-xs">
                      {r.source_status.map((s, i) => (
                        <li key={i}>
                          {String(s.source_id ?? '?')}: {String(s.health ?? '?')}
                          {s.latest_record_date ? `, latest ${String(s.latest_record_date)}` : ''}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                <details className="rounded border border-line">
                  <summary className="cursor-pointer px-3 py-2 text-xs font-semibold">Exact request</summary>
                  <pre className="max-h-80 overflow-auto border-t border-line bg-surface-2 p-3 text-[11px] leading-snug">{JSON.stringify(r.request, null, 2)}</pre>
                </details>
              </div>
            ) : null}
          </div>
        </div>
      </aside>
    </div>
  )
}
