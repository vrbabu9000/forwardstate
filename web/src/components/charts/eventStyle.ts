import type { Event } from '../../api/types'

export type MarkerClass = 'scheduled' | 'anticipated' | 'unexpected' | 'derived'

export const MARKER_LABEL: Record<MarkerClass, string> = {
  scheduled: 'Scheduled',
  anticipated: 'Anticipated',
  unexpected: 'Unexpected',
  derived: 'Derived (price shock)',
}

export const MARKER_VAR: Record<MarkerClass, string> = {
  scheduled: '--ev-scheduled',
  anticipated: '--ev-anticipated',
  unexpected: '--ev-unexpected',
  derived: '--ev-derived',
}

export function markerClass(e: Event): MarkerClass {
  if (e.origin === 'derived' || e.subtype === 'price_shock') return 'derived'
  return e.event_class
}

export function eventDate(e: Event): string {
  return (e.occurred_at ?? e.scheduled_at ?? e.published_at ?? e.available_at).slice(0, 10)
}
