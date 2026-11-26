import { describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server } from '../mocks/server'
import { renderApp } from './render'

describe('UI-01 Stock research', () => {
  it('renders prices, events, peers, analysts and three scenario horizons for JPM', async () => {
    renderApp('/research/JPM')
    expect(await screen.findByRole('heading', { name: 'JPMorgan Chase & Co.' })).toBeInTheDocument()
    expect(await screen.findByTestId('price-chart')).toBeInTheDocument()
    expect(await screen.findByRole('article', { name: 'Short term forecast' })).toBeInTheDocument()
    expect(screen.getByRole('article', { name: 'Medium term forecast' })).toBeInTheDocument()
    expect(screen.getByRole('article', { name: 'Long term forecast' })).toBeInTheDocument()
    expect(screen.getByText(/Views, not facts/)).toBeInTheDocument()
    expect(screen.getAllByText('Replay mode — historical data, not live').length).toBeGreaterThan(0)
    // Long horizon is low confidence and says why.
    expect(await screen.findByText('Low confidence.')).toBeInTheDocument()
    // At least one timestamped event in the list (AC-01).
    const events = await screen.findByText('Events in range, newest first')
    expect(within(events.parentElement!).getAllByRole('button').length).toBeGreaterThan(0)
  })

  it('shows an unavailable forecast with its reason instead of a number', async () => {
    renderApp('/research/C')
    expect(await screen.findByRole('heading', { name: 'Citigroup Inc.' })).toBeInTheDocument()
    expect(await screen.findByText('Forecast unavailable.')).toBeInTheDocument()
    expect(screen.getByText(/Not enough clean history for a 2-year view/)).toBeInTheDocument()
  })

  it('re-runs POST /api/forecast when an assumption changes (AC-02)', async () => {
    const bodies: Array<{ assumptions?: { rate_change_bps?: number } }> = []
    server.events.on('request:start', async ({ request }) => {
      if (request.method === 'POST' && request.url.endsWith('/api/forecast')) bodies.push(await request.clone().json())
    })
    renderApp('/research/JPM')
    await screen.findByRole('article', { name: 'Short term forecast' })
    await waitFor(() => expect(bodies.length).toBe(1))
    const input = screen.getByLabelText(/Fed funds change/)
    fireEvent.change(input, { target: { value: '50' } })
    await waitFor(() => expect(bodies.length).toBe(2), { timeout: 3000 })
    expect(bodies[1].assumptions?.rate_change_bps).toBe(50)
    expect((await screen.findAllByText(/Fed funds \+50 bps/)).length).toBeGreaterThan(0)
    server.events.removeAllListeners()
  })
})

describe('UI-02 Portfolio', () => {
  it('loads the default portfolio and evaluates it', async () => {
    renderApp('/portfolio')
    expect(await screen.findByRole('heading', { name: 'Portfolio' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Evaluate' }))
    expect(await screen.findByRole('heading', { name: 'Current portfolio' })).toBeInTheDocument()
    expect(screen.getByText('CVaR 95')).toBeInTheDocument()
    expect(screen.getByText('Scenario P&L')).toBeInTheDocument()
  })

  it('shows an error when holdings add up to more than 100%', async () => {
    renderApp('/portfolio')
    const w = await screen.findByLabelText('Weight percent for JPM')
    fireEvent.change(w, { target: { value: '50' } })
    expect(await screen.findByText(/Weights add up to 115.0%. They must add up to 100%/)).toBeInTheDocument()
  })

  it('rejects infeasible limits inline at the field (AC-04)', async () => {
    renderApp('/portfolio')
    const min = await screen.findByLabelText(/Min cash/)
    fireEvent.change(min, { target: { value: '60' } })
    fireEvent.change(screen.getByLabelText(/Max cash/), { target: { value: '50' } })
    await userEvent.click(screen.getByRole('button', { name: 'Evaluate' }))
    expect(await screen.findByText(/This portfolio cannot be evaluated as entered/)).toBeInTheDocument()
    expect(screen.getByText(/Minimum cash is above maximum cash/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Min cash/)).toHaveAttribute('aria-invalid', 'true')
  })

  it('lists candidate allocations as options, not instructions', async () => {
    renderApp('/portfolio')
    await userEvent.click(await screen.findByRole('button', { name: 'Find candidates' }))
    expect(await screen.findByRole('heading', { name: 'Candidate allocations' })).toBeInTheDocument()
    expect(screen.getByText(/Options to consider — not instructions/)).toBeInTheDocument()
    expect(screen.getByText('Defensive')).toBeInTheDocument()
  })
})

describe('UI-03 Events & alerts', () => {
  it('shows alert detail with alternatives and the decision boundary', async () => {
    renderApp('/alerts')
    expect(await screen.findByRole('heading', { name: 'Alternatives compared' })).toBeInTheDocument()
    expect(screen.getByText('Hold (no change)')).toBeInTheDocument()
    expect(screen.getByText('Move 25% to cash')).toBeInTheDocument()
    expect(screen.getByText('Move 50% to cash')).toBeInTheDocument()
    expect(screen.getAllByText(/Options to consider — not instructions/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/decision support only/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/simulated, uncalibrated/).length).toBeGreaterThan(0)
  })

  it('replays a shock and opens an alert from a marker (AC-05)', async () => {
    renderApp('/alerts')
    const run = await screen.findByRole('button', { name: 'Run replay' })
    await waitFor(() => expect(run).toBeEnabled())
    await userEvent.click(run)
    const list = await screen.findByText('Alerts raised during the replay', {}, { timeout: 5000 })
    const first = within(list.parentElement!).getAllByRole('button')[0]
    await userEvent.click(first)
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Alternatives compared' })).toBeInTheDocument())
  })

  it('acknowledges a new alert', async () => {
    renderApp('/alerts')
    const ack = await screen.findByRole('button', { name: 'Acknowledge' })
    await waitFor(() => expect(ack).toBeEnabled())
    await userEvent.click(ack)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Acknowledge' })).toBeDisabled())
  })
})

describe('UI-04 Settings and provenance', () => {
  it('renders settings and the sources freshness table', async () => {
    renderApp('/settings')
    expect(await screen.findByRole('heading', { name: 'Settings' })).toBeInTheDocument()
    expect(await screen.findByText('Sources and freshness')).toBeInTheDocument()
    expect(await screen.findByText('Stale')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Save settings' }))
    expect(await screen.findByText('Settings saved.')).toBeInTheDocument()
  })

  it('opens a run and reproduces it with a match (AC-06)', async () => {
    renderApp('/research/JPM')
    await screen.findByRole('article', { name: 'Short term forecast' })
    await userEvent.click(screen.getByRole('button', { name: /How this was computed/ }))
    const dialog = await screen.findByRole('dialog', { name: 'Run provenance' })
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Reproduce' }))
    expect(await within(dialog).findByText('Match.')).toBeInTheDocument()
    expect(within(dialog).getByText('Model version')).toBeInTheDocument()
  })
})
