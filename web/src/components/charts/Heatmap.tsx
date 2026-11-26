import { num } from '../../lib/format'

/** Correlation matrix as a table; colour encodes sign and size, the number is always shown. */
export default function Heatmap({ matrix }: { matrix: Record<string, Record<string, number>> }) {
  const ids = Object.keys(matrix)
  if (!ids.length) return <p className="text-sm text-muted">No correlation data.</p>
  const bg = (v: number) => {
    const pctv = Math.round(Math.min(1, Math.abs(v)) * 70)
    const c = v >= 0 ? 'var(--accent)' : 'var(--pes)'
    return `color-mix(in srgb, ${c} ${pctv}%, var(--surface))`
  }
  return (
    <div className="scroll-x">
      <table className="text-xs tabular-nums" aria-label="Correlation of daily returns, last 5 years">
        <thead>
          <tr>
            <th className="p-1" />
            {ids.map((c) => (
              <th key={c} scope="col" className="p-1 text-center font-semibold text-muted">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ids.map((r) => (
            <tr key={r}>
              <th scope="row" className="p-1 pr-2 text-left font-semibold text-muted">
                {r}
              </th>
              {ids.map((c) => {
                const v = matrix[r]?.[c] ?? 0
                return (
                  <td key={c} className="h-9 w-12 min-w-11 text-center" style={{ background: bg(v), color: Math.abs(v) > 0.6 ? 'var(--accent-ink)' : 'var(--ink)' }}>
                    {num(v, 2)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
