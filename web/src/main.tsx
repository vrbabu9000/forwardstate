import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import App, { makeQueryClient } from './App'
import './index.css'

async function start() {
  // VITE_USE_MOCKS=1 serves every /api route from synthetic in-browser mocks (MSW).
  if (import.meta.env.VITE_USE_MOCKS === '1') {
    const { startMocks } = await import('./mocks/browser')
    await startMocks()
  }
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <BrowserRouter>
        <App client={makeQueryClient()} />
      </BrowserRouter>
    </StrictMode>,
  )
}

void start()
