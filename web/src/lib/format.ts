const pctFmt = new Intl.NumberFormat('en-US', { style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 })
const moneyFmt = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const priceFmt = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 })

export const DASH = '—'

export function pct(v: number | null | undefined, signed = false): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH
  const s = pctFmt.format(v)
  return signed && v > 0 ? `+${s}` : s
}

export function money(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH
  return moneyFmt.format(v)
}

export function price(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH
  return priceFmt.format(v)
}

export function num(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH
  return v.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function signed(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH
  const s = num(v, digits)
  return v > 0 ? `+${s}` : s
}

/** 2025-11-21 or an ISO datetime -> "21 Nov 2025". */
export function day(v: string | null | undefined): string {
  if (!v) return DASH
  const d = new Date(v.length === 10 ? `${v}T12:00:00Z` : v)
  if (Number.isNaN(d.getTime())) return v
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
}

export function dateTime(v: string | null | undefined): string {
  if (!v) return DASH
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return v
  // Market times are shown in New York time, the exchange's clock (as-of = 23:59 ET on a date).
  return `${d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'America/New_York' })}, ${d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'America/New_York' })} ET`
}

export function shortHash(h: string | null | undefined): string {
  return h ? h.slice(0, 12) : DASH
}

export function titleCase(s: string): string {
  const t = s.replace(/_/g, ' ')
  return t.charAt(0).toUpperCase() + t.slice(1)
}
