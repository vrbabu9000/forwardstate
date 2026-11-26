import { getResponse } from 'msw'
import { setupWorker } from 'msw/browser'
import { handlers } from './handlers'

export const worker = setupWorker(...handlers)

/**
 * Start the synthetic mock API. Prefers the MSW service worker; where a browser cannot
 * register service workers (some embedded or private windows), falls back to answering
 * /api fetches in the page with the very same handlers.
 */
export async function startMocks(): Promise<'worker' | 'in-page'> {
  try {
    await worker.start({ onUnhandledRequest: 'bypass', quiet: true })
    return 'worker'
  } catch (err) {
    console.warn('[mocks] Service worker unavailable, serving mocks in-page instead.', err)
    const realFetch = window.fetch.bind(window)
    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const req = new Request(input, init)
      if (new URL(req.url).pathname.startsWith('/api/')) {
        const res = await getResponse(handlers, req)
        if (res) return res
      }
      return realFetch(input, init)
    }
    return 'in-page'
  }
}
