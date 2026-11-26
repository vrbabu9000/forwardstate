import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { appText, renderApp } from './render'

// No trading UI: the words below must never appear in the app. The decision-boundary notice is
// excluded because its job is to say the app does NOT do these things.
const FORBIDDEN = /\b(buy|buys|buying|bought|sell|sells|selling|sold|trade|trades|trading|traded|execute|executes|executing|execution|order|orders|ordered|ordering)\b/i

function check(where: string) {
  const text = appText()
  const m = FORBIDDEN.exec(text)
  expect(m ? `${where}: "${text.slice(Math.max(0, m.index - 40), m.index + 40)}"` : null).toBeNull()
}

describe('no trading wording anywhere', () => {
  it('research view', async () => {
    renderApp('/research/JPM')
    await screen.findByRole('article', { name: 'Long term forecast' })
    await screen.findByText('Rates, percent')
    check('research')
  })

  it('portfolio view with candidates', async () => {
    renderApp('/portfolio')
    await userEvent.click(await screen.findByRole('button', { name: 'Find candidates' }))
    await screen.findByRole('heading', { name: 'Candidate allocations' })
    check('portfolio')
  })

  it('alerts view with replay', async () => {
    renderApp('/alerts')
    await screen.findByRole('heading', { name: 'Alternatives compared' })
    await userEvent.click(screen.getByRole('button', { name: 'Run replay' }))
    await screen.findByText('Alerts raised during the replay', {}, { timeout: 5000 })
    check('alerts')
  })

  it('settings view and provenance drawer', async () => {
    renderApp('/settings')
    await screen.findByText('Stale')
    check('settings')
    await userEvent.click(screen.getByRole('button', { name: 'Runs' }))
    await screen.findByRole('dialog', { name: 'Run provenance' })
    check('provenance')
  })

  it('has no buttons that look like trading actions', async () => {
    renderApp('/alerts')
    await screen.findByRole('heading', { name: 'Alternatives compared' })
    for (const b of screen.getAllByRole('button')) expect(b.textContent ?? '').not.toMatch(FORBIDDEN)
  })
})
