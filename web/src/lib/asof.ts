/**
 * The API takes `as_of` as a date in query strings (meaning 23:59 New York time that day),
 * but request bodies are typed as timezone-aware datetimes. Convert a picked date to that
 * instant with the correct New York offset (EST or EDT).
 */
export function asOfDateToIso(d: string): string {
  const probe = new Date(`${d}T23:59:00Z`)
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', timeZoneName: 'shortOffset' })
    .formatToParts(probe)
  const tz = parts.find((p) => p.type === 'timeZoneName')?.value ?? 'GMT-5'
  const m = /GMT([+-]\d{1,2})(?::(\d{2}))?/.exec(tz)
  const h = m ? Number(m[1]) : -5
  const mins = m?.[2] ?? '00'
  const sign = h < 0 ? '-' : '+'
  return `${d}T23:59:00${sign}${String(Math.abs(h)).padStart(2, '0')}:${mins}`
}

/** Accepts a date or an ISO datetime; returns the YYYY-MM-DD part in New York time. */
export function isoToNyDate(v: string): string {
  if (v.length === 10) return v
  const d = new Date(v)
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(d)
}
