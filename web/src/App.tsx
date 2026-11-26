import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Navigate, Route, Routes } from 'react-router'
import { Shell } from './components/Shell'
import { AppProvider } from './state/app'
import Research from './views/Research'
import Portfolio from './views/Portfolio'
import Alerts from './views/Alerts'
import Settings from './views/Settings'

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 30_000 },
      mutations: { retry: 0 },
    },
  })
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Navigate to="/research/JPM" replace />} />
        <Route path="research" element={<Navigate to="/research/JPM" replace />} />
        <Route path="research/:securityId" element={<Research />} />
        <Route path="portfolio" element={<Portfolio />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="settings" element={<Settings />} />
        <Route
          path="*"
          element={
            <div className="panel p-6">
              <h1 className="text-lg font-semibold">Page not found</h1>
              <p className="text-sm text-muted">Use the menu to open one of the four views.</p>
            </div>
          }
        />
      </Route>
    </Routes>
  )
}

export default function App({ client }: { client: QueryClient }) {
  return (
    <QueryClientProvider client={client}>
      <AppProvider>
        <AppRoutes />
      </AppProvider>
    </QueryClientProvider>
  )
}
