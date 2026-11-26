"""FinancialsModule: universe, taxonomy, exposure (peer transmission)."""

from __future__ import annotations

from forwardstate.contracts import Event, EventClass, EventScope, EventStatus, SecurityRole
from forwardstate.industries import get_sector, registered_sectors
from forwardstate.industries.financials import FinancialsModule
from forwardstate.pit import et
from forwardstate.services import SectorModule
from forwardstate.testing import FixtureStore, synthetic_as_of

BANKS = ["JPM", "BAC", "C", "MS", "GS"]


def _event(scope: EventScope, affected: list[str]) -> Event:
    from datetime import date

    t = et(date(2023, 5, 1), 10)
    return Event(source_id="test", available_at=t, event_id="e1", event_class=EventClass.UNEXPECTED,
                 subtype="breaking_news", title="t", status=EventStatus.OCCURRED, scope=scope,
                 occurred_at=t, affected_security_ids=affected)


def test_registered_and_protocol():
    mod = get_sector("financials")
    assert "financials" in registered_sectors()
    assert isinstance(mod, SectorModule)


def test_universe_and_benchmarks():
    mod = FinancialsModule()
    assert [s.security_id for s in mod.universe()] == BANKS
    assert {s.role for s in mod.universe()} == {SecurityRole.FOCAL, SecurityRole.PEER}
    bms = mod.benchmarks()
    assert [s.security_id for s in bms] == ["SPY", "XLF"]
    assert all(not s.investable and s.role == SecurityRole.BENCHMARK for s in bms)


def test_taxonomy_contains_required_subtypes():
    tax = FinancialsModule().event_taxonomy()
    for sub in ["quarterly_results", "fomc_meeting", "filing_10q", "filing_10k"]:
        assert sub in tax[EventClass.SCHEDULED]
    for sub in ["rate_change", "regulatory_development"]:
        assert sub in tax[EventClass.ANTICIPATED]
    for sub in ["price_shock", "filing_8k", "sector_stress", "breaking_news"]:
        assert sub in tax[EventClass.UNEXPECTED]
    assert FinancialsModule().classify("price_shock") == EventClass.UNEXPECTED


def test_exposure_firm_sector_market():
    mod = FinancialsModule()
    firm = mod.exposure(_event(EventScope.FIRM, ["JPM"]), BANKS + ["CASH"])
    assert firm["JPM"] == 1.0 and all(firm[s] == 0.3 for s in BANKS[1:]) and firm["CASH"] == 0.0
    assert set(mod.exposure(_event(EventScope.SECTOR, BANKS), BANKS).values()) == {1.0}
    # market scope without data falls back to 1.0
    assert set(mod.exposure(_event(EventScope.MARKET, BANKS), BANKS).values()) == {1.0}
    rets = FixtureStore().returns(BANKS + ["SPY"], synthetic_as_of())
    mk = mod.exposure(_event(EventScope.MARKET, BANKS), BANKS, rets)
    assert all(0.0 <= v <= 1.0 for v in mk.values())
    assert len(set(mk.values())) > 1  # beta-based, not flat
