import { Area, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { SecurityForecast } from '../../api/types'
import { price } from '../../lib/format'

/**
 * Fan chart: price paths from today to the horizon for the three scenarios, with the
 * stated 80% interval as the outer band. Spread widens with the square root of time.
 */
export default function FanChart({ f, height = 180 }: { f: SecurityForecast; height?: number }) {
  const s0 = f.start_price
  const by = Object.fromEntries((f.scenarios ?? []).map((s) => [s.scenario, s]))
  if (!s0 || !by.base || !by.optimistic || !by.pessimistic) return null
  const H = f.horizon_trading_days
  const lb = Math.log(by.base.projected_price / s0)
  const steps = 24
  const data = Array.from({ length: steps + 1 }, (_, k) => {
    const t = k / steps
    const r = Math.sqrt(t)
    const at = (target: number) => Math.exp(lb * t + (Math.log(target / s0) - lb) * r) * s0
    const pes = at(by.pessimistic.projected_price)
    const opt = at(by.optimistic.projected_price)
    return {
      day: Math.round(t * H),
      outer: [at(by.pessimistic.interval_low), at(by.optimistic.interval_high)] as [number, number],
      inner: [pes, opt] as [number, number],
      base: at(by.base.projected_price),
      opt,
      pes,
    }
  })
  return (
    <div style={{ height }} className="w-full" role="img" aria-label={`Fan chart for ${f.security_id} over ${H} market days: base ${price(by.base.projected_price)}, range ${price(by.pessimistic.interval_low)} to ${price(by.optimistic.interval_high)}`}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
          <XAxis dataKey="day" type="number" domain={[0, H]} tickLine={false} axisLine={{ stroke: 'var(--line)' }} tickFormatter={(d: number) => `${d}d`} />
          <YAxis width={52} tickLine={false} axisLine={false} domain={['auto', 'auto']} tickFormatter={(v: number) => `$${Math.round(v)}`} />
          <Tooltip
            contentStyle={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 4, fontSize: 12 }}
            labelFormatter={(d) => `Day ${d}`}
            formatter={(v, name) => {
              const val = Array.isArray(v) ? `${price(Number(v[0]))} – ${price(Number(v[1]))}` : price(Number(v))
              const label = name === 'outer' ? '80% interval' : name === 'inner' ? 'Pessimistic to optimistic' : String(name)
              return [val, label]
            }}
          />
          <Area dataKey="outer" stroke="none" fill="var(--accent)" fillOpacity={0.1} isAnimationActive={false} />
          <Area dataKey="inner" stroke="none" fill="var(--accent)" fillOpacity={0.18} isAnimationActive={false} />
          <ReferenceLine y={s0} stroke="var(--line-strong)" strokeDasharray="2 3" />
          <Line dataKey="opt" name="Optimistic" stroke="var(--opt)" strokeWidth={1.5} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
          <Line dataKey="pes" name="Pessimistic" stroke="var(--pes)" strokeWidth={1.5} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
          <Line dataKey="base" name="Base" stroke="var(--base)" strokeWidth={2} dot={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
