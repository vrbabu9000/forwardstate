import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { PeerComparison } from '../../api/types'
import { day, num } from '../../lib/format'

const COLORS = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)', 'var(--series-5)', 'var(--series-6)']

export function peerColor(i: number) {
  return COLORS[i % COLORS.length]
}

export default function PeerChart({ data, height = 260 }: { data: PeerComparison; height?: number }) {
  const ids = data.series.map((s) => s.security_id)
  const maps = data.series.map((s) => new Map(s.points.map((p) => [p.date, p.value])))
  const dates = data.series[0]?.points.map((p) => p.date) ?? []
  const stride = Math.max(1, Math.floor(dates.length / 180))
  const rows = dates
    .filter((_, i) => i % stride === 0 || i === dates.length - 1)
    .map((d) => Object.fromEntries([['date', d], ...ids.map((id, i) => [id, maps[i].get(d) ?? null])]))
  return (
    <div style={{ height }} className="w-full" role="img" aria-label={`Peer prices rebased to 100 from ${day(data.base_date)}`}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--line)" />
          <XAxis dataKey="date" tickLine={false} axisLine={{ stroke: 'var(--line)' }} minTickGap={40} tickFormatter={(d: string) => d.slice(0, 7)} />
          <YAxis width={40} tickLine={false} axisLine={false} domain={['auto', 'auto']} />
          <ReferenceLine y={100} stroke="var(--line-strong)" />
          <Tooltip
            contentStyle={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 4, fontSize: 12 }}
            labelFormatter={(d) => day(String(d))}
            formatter={(v, n) => [num(Number(v), 1), String(n)]}
          />
          <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
          {ids.map((id, i) => (
            <Line
              key={id}
              dataKey={id}
              stroke={peerColor(i)}
              strokeWidth={i === 0 ? 2.5 : 1.25}
              strokeDasharray={id === 'XLF' ? '4 3' : undefined}
              dot={false}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
