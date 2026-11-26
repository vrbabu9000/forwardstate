import '@testing-library/jest-dom/vitest'
import { afterAll, afterEach, beforeAll, vi } from 'vitest'
import { cleanup } from '@testing-library/react'
import { server } from '../mocks/server'
import { resetDb } from '../mocks/engine'

// lightweight-charts draws on canvas, which jsdom lacks. Replace it with a list of markers.
vi.mock('../components/charts/PriceChart', async () => {
  const React = await import('react')
  return {
    default: ({ events, label }: { events: Array<{ event_id: string; title: string }>; label: string }) =>
      React.createElement('div', { role: 'img', 'aria-label': label, 'data-testid': 'price-chart' }, `${events.length} markers`),
  }
})

class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
;(globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver ??= RO

if (!window.matchMedia) {
  window.matchMedia = (q: string) =>
    ({ matches: false, media: q, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false }) as unknown as MediaQueryList
}
window.HTMLElement.prototype.scrollIntoView ??= function () {}

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  cleanup()
  server.resetHandlers()
  resetDb()
})
afterAll(() => server.close())
