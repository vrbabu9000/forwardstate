import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { AppProvider } from '../state/app'
import { AppRoutes } from '../App'

export function renderApp(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: 0 } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AppProvider>
          <AppRoutes />
        </AppProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** Visible text of the app, minus the decision-boundary notices (which must name what the app does not do). */
export function appText(root: HTMLElement = document.body): string {
  const clone = root.cloneNode(true) as HTMLElement
  clone.querySelectorAll('[data-boundary]').forEach((n) => n.remove())
  clone.querySelectorAll('script,style').forEach((n) => n.remove())
  return clone.textContent ?? ''
}
