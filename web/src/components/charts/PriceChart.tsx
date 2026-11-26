import { useEffect, useRef } from 'react'
import {
  ColorType,
  CrosshairMode,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'
import type { Event, PricePoint } from '../../api/types'
import { cssVar } from '../../state/theme'
import { MARKER_VAR, eventDate, markerClass } from './eventStyle'
import { useThemeVersion } from './useThemeVersion'

interface Props {
  points: PricePoint[]
  events: Event[]
  onSelectEvent: (e: Event) => void
  height?: number
  label: string
}

/** Adjusted-close line with one marker per event day, coloured by event class. */
export default function PriceChart({ points, events, onSelectEvent, height = 320, label }: Props) {
  const el = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const themeV = useThemeVersion()
  const selectRef = useRef(onSelectEvent)
  selectRef.current = onSelectEvent

  useEffect(() => {
    if (!el.current || points.length === 0) return
    const ink = cssVar('--muted', '#5a6b76')
    const line = cssVar('--line', '#d2dbdf')
    const chart = createChart(el.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: ink,
        fontFamily: getComputedStyle(document.body).fontFamily,
        fontSize: 11,
        attributionLogo: true,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: line } },
      rightPriceScale: { borderColor: line },
      timeScale: { borderColor: line, fixLeftEdge: true, fixRightEdge: true },
      crosshair: { mode: CrosshairMode.Magnet },
      localization: { priceFormatter: (p: number) => `$${p.toFixed(2)}` },
    })
    chartRef.current = chart
    const series = chart.addSeries(LineSeries, { color: cssVar('--accent', '#1c5a78'), lineWidth: 2, priceLineVisible: false })
    series.setData(points.map((p) => ({ time: p.date as Time, value: p.close })))

    // Snap each event to the first trading day on or after it, inside the data range.
    const dates = points.map((p) => p.date)
    const byDay = new Map<string, Event[]>()
    for (const e of events) {
      const d = eventDate(e)
      if (d < dates[0] || d > dates[dates.length - 1]) continue
      let lo = 0
      let hi = dates.length - 1
      while (lo < hi) {
        const mid = (lo + hi) >> 1
        if (dates[mid] < d) lo = mid + 1
        else hi = mid
      }
      const key = dates[lo]
      byDay.set(key, [...(byDay.get(key) ?? []), e])
    }
    const markers: SeriesMarker<Time>[] = [...byDay.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([d, evs]) => {
        const cls = markerClass(evs[0])
        return {
          time: d as Time,
          position: cls === 'scheduled' ? 'belowBar' : 'aboveBar',
          color: cssVar(MARKER_VAR[cls]),
          shape: cls === 'unexpected' || cls === 'derived' ? 'arrowDown' : cls === 'anticipated' ? 'square' : 'circle',
          id: d,
          size: 1,
        }
      })
    const m = createSeriesMarkers(series, markers)
    chart.subscribeClick((param) => {
      const t = (param.hoveredObjectId as string | undefined) ?? (typeof param.time === 'string' ? param.time : undefined)
      if (!t) return
      const evs = byDay.get(t)
      if (evs?.length) selectRef.current(evs[0])
    })
    chart.timeScale().fitContent()
    return () => {
      m.detach()
      chart.remove()
      chartRef.current = null
    }
  }, [points, events, themeV])

  return <div ref={el} role="img" aria-label={label} style={{ height }} className="w-full" />
}
