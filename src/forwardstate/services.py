"""Service interfaces between layers (BRD p.11). Owned by the integrator.

Each layer implements one Protocol. Layers depend only on these Protocols and on
``forwardstate.contracts``, never on each other's internals. Wiring happens in
``forwardstate.api.container`` (Wave 2).

Point-in-time rule: every read takes ``as_of`` and returns only records with
``available_at <= as_of``.

DataFrame conventions (all returned frames):
- ``prices``: one row per (security_id, trading_date), sorted by date. Columns:
  ``security_id, trading_date (datetime64[ns], naive date), raw_close, adj_close, volume,
  available_at (datetime64[ns, UTC]), origin``. ``adj_close`` is adjusted for splits and
  dividends known as of ``as_of`` (D007).
- ``returns``: wide frame, index = trading_date, columns = security_id, simple daily returns
  computed from ``adj_close``.
- ``observations``: ``metric_id, security_id, period_end, value, unit, available_at, origin``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd

from .contracts import (
    Alert,
    AlertRule,
    AlertStatus,
    AlertTransition,
    AnalystObservation,
    CorporateAction,
    Event,
    EventClass,
    ForecastRun,
    Horizon,
    ImpactEstimate,
    Observation,
    Portfolio,
    PortfolioEvaluation,
    PriceBar,
    ReplayResult,
    ScenarioAssumptions,
    Security,
    SourceStatus,
)


@runtime_checkable
class PointInTimeStore(Protocol):
    """Layer 2. Implementations: ``storage`` (DuckDB/Parquet) and
    ``testing.fixture_store.FixtureStore`` (in-memory synthetic)."""

    def securities(self, sector: str | None = None) -> list[Security]: ...

    def prices(
        self,
        security_ids: list[str],
        as_of: datetime,
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame: ...

    def returns(
        self,
        security_ids: list[str],
        as_of: datetime,
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame: ...

    def corporate_actions(self, security_ids: list[str], as_of: datetime) -> list[CorporateAction]: ...

    def observations(
        self,
        metric_ids: list[str],
        as_of: datetime,
        security_id: str | None = None,
        start: date | None = None,
    ) -> list[Observation]: ...

    def events(
        self,
        as_of: datetime,
        security_ids: list[str] | None = None,
        event_classes: list[EventClass] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Event]: ...

    def analyst_observations(
        self, as_of: datetime, security_ids: list[str] | None = None
    ) -> list[AnalystObservation]: ...

    def latest_as_of(self) -> datetime:
        """Latest available_at across price data: the default 'now' for replay mode."""
        ...

    def source_status(self) -> list[SourceStatus]: ...

    # Writes (ingest only)
    def upsert_prices(self, bars: list[PriceBar]) -> int: ...
    def upsert_corporate_actions(self, actions: list[CorporateAction]) -> int: ...
    def upsert_observations(self, obs: list[Observation]) -> int: ...
    def upsert_events(self, events: list[Event]) -> int: ...
    def upsert_analyst_observations(self, obs: list[AnalystObservation]) -> int: ...


@runtime_checkable
class EventService(Protocol):
    """Layer 3: classification, entity mapping, timeline, impact estimates."""

    def list_events(
        self,
        as_of: datetime,
        security_ids: list[str] | None = None,
        event_classes: list[EventClass] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Event]:
        """Stored events plus derived ones (e.g. price shocks), deduplicated, as of ``as_of``."""
        ...

    def impact_estimates(
        self, as_of: datetime, event_id: str | None = None, security_id: str | None = None
    ) -> list[ImpactEstimate]: ...


@runtime_checkable
class ForecastService(Protocol):
    """Layer 4: per-asset scenario forecasts and correlated joint return simulations."""

    def forecast(
        self,
        as_of: datetime,
        security_ids: list[str],
        horizons: list[Horizon],
        assumptions: ScenarioAssumptions,
    ) -> ForecastRun: ...

    def simulate_joint_returns(
        self,
        as_of: datetime,
        security_ids: list[str],
        horizon_days: int,
        assumptions: ScenarioAssumptions,
        n_paths: int = 2000,
        seed: int = 0,
    ) -> np.ndarray:
        """Correlated simulated *daily* return paths, shape (n_paths, horizon_days, n_assets),
        column order = ``security_ids``. Must preserve cross-asset correlation (PF-03), e.g. by
        block-bootstrapping whole days of joint history, then applying assumption shifts.
        ``CASH`` (if present) gets the configured cash yield and zero volatility."""
        ...


@runtime_checkable
class PortfolioService(Protocol):
    """Layer 5: portfolio evaluation and candidate allocations."""

    def evaluate_portfolio(
        self, portfolio: Portfolio, as_of: datetime, assumptions: ScenarioAssumptions
    ) -> PortfolioEvaluation:
        """Risk of the current portfolio + candidates ('no change' always included)."""
        ...

    def optimize(
        self, portfolio: Portfolio, as_of: datetime, assumptions: ScenarioAssumptions
    ) -> PortfolioEvaluation:
        """Like evaluate_portfolio but candidates come from the optimizer under constraints.
        Infeasible constraints return feasible=False with issues; never silently changed."""
        ...


@runtime_checkable
class AlertService(Protocol):
    """Layer 6 (logic): rule evaluation, lifecycle, replay. Notifies only; never trades."""

    model_version: str

    def rules(self) -> list[AlertRule]: ...

    def set_rules(self, rules: list[AlertRule]) -> None:
        """Replace the active rule set; keeps the alert inbox and lifecycle history."""
        ...

    def transitions(self, alert_id: str | None = None) -> list[AlertTransition]:
        """Lifecycle audit trail, oldest first."""
        ...

    def evaluate_alerts(
        self,
        portfolio: Portfolio,
        as_of: datetime,
        assumptions: ScenarioAssumptions,
        rule_ids: list[str] | None = None,
    ) -> list[Alert]: ...

    def list_alerts(self, status: AlertStatus | None = None) -> list[Alert]: ...

    def transition(self, alert_id: str, to_status: AlertStatus, note: str | None = None) -> Alert: ...

    def replay(
        self,
        portfolio: Portfolio,
        start: date,
        end: date,
        assumptions: ScenarioAssumptions,
        step_trading_days: int = 1,
        rule_ids: list[str] | None = None,
    ) -> ReplayResult:
        """Walk forward through history; at each step use only data available by that date."""
        ...


@runtime_checkable
class SectorModule(Protocol):
    """Industry plug-in contract (BRD p.11, AC-07). Registered in ``forwardstate.industries``."""

    sector_id: str

    def universe(self) -> list[Security]: ...

    def benchmarks(self) -> list[Security]: ...

    def event_taxonomy(self) -> dict[EventClass, list[str]]: ...

    def indicators(self) -> list[str]: ...

    def exposure(self, event: Event, security_ids: list[str]) -> dict[str, float]:
        """Sensitivity weight (0..1) of each security to an event; used for peer transmission."""
        ...
