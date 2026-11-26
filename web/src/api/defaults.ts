import type { Constraints, ScenarioAssumptions } from './types'

// Mirrors the pydantic defaults in src/forwardstate/contracts (Constraints, ScenarioAssumptions).
// Used only until /api/settings has loaded.
export const DEFAULT_CONSTRAINTS: Constraints = {
  max_position_weight: 0.4,
  min_cash_weight: 0,
  max_cash_weight: 1,
  max_turnover: null,
  risk_aversion: 3,
  cash_annual_yield: 0,
  transaction_cost_bps: 5,
  long_only: true,
  allow_leverage: false,
}

export const NEUTRAL_ASSUMPTIONS: ScenarioAssumptions = {
  rate_change_bps: 0,
  earnings_surprise_pct: 0,
  market_return_shift_pct: 0,
  volatility_multiplier: 1,
  analyst_weight: 0.25,
  lookback_years: 5,
  notes: null,
}
