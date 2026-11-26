"""DuckDBStore: equivalence with FixtureStore, no look-ahead, append-only restatements."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from forwardstate.contracts import (
    CorporateAction,
    CorporateActionKind,
    DataOrigin,
    Event,
    EventClass,
    EventScope,
    EventStatus,
    Observation,
    PriceBar,
    SecurityRole,
    SourceHealth,
)
from forwardstate.pit import UTC, as_of_for_date, bar_available_at, et
from forwardstate.services import PointInTimeStore
from forwardstate.storage import PRICE_COLUMNS, DuckDBStore, open_store
from forwardstate.testing import FixtureStore, build_synthetic_dataset

AS_OF_DATES = [date(2022, 3, 1), date(2022, 6, 30), date(2023, 3, 10), date(2023, 3, 14),
               date(2024, 12, 31)]


@pytest.fixture(scope="module")
def stores(tmp_path_factory):
    ds = build_synthetic_dataset()
    db = DuckDBStore(tmp_path_factory.mktemp("db") / "fs.duckdb", securities=ds.securities)
    db.upsert_prices(ds.bars)
    db.upsert_corporate_actions(ds.actions)
    db.upsert_observations(ds.observations)
    db.upsert_events(ds.events)
    db.upsert_analyst_observations(ds.analyst)
    return db, FixtureStore(ds), [s.security_id for s in ds.securities]


def _dump(recs):
    return sorted((r.model_dump(mode="json", exclude={"ingested_at"}) for r in recs), key=repr)


def test_implements_protocol(stores):
    assert isinstance(stores[0], PointInTimeStore)


@pytest.mark.parametrize("d", AS_OF_DATES)
def test_equivalent_to_fixture_store(stores, d):
    db, fx, ids = stores
    as_of = as_of_for_date(d)
    p_db, p_fx = db.prices(ids, as_of), fx.prices(ids, as_of)
    assert list(p_db.columns) == PRICE_COLUMNS
    pd.testing.assert_frame_equal(p_db, p_fx)
    pd.testing.assert_frame_equal(db.prices(["JPM", "BAC"], as_of, start=date(2022, 2, 1)),
                                  fx.prices(["JPM", "BAC"], as_of, start=date(2022, 2, 1)))
    pd.testing.assert_frame_equal(db.returns(ids, as_of), fx.returns(ids, as_of))
    assert _dump(db.events(as_of)) == _dump(fx.events(as_of))
    assert _dump(db.events(as_of, security_ids=["JPM"], event_classes=[EventClass.SCHEDULED])) \
        == _dump(fx.events(as_of, security_ids=["JPM"], event_classes=[EventClass.SCHEDULED]))
    assert _dump(db.analyst_observations(as_of)) == _dump(fx.analyst_observations(as_of))
    m = ["DFF", "DGS2", "DGS10", "eps_surprise_pct"]
    assert _dump(db.observations(m, as_of)) == _dump(fx.observations(m, as_of))
    assert _dump(db.observations(["eps_surprise_pct"], as_of, security_id="JPM")) == \
        _dump(fx.observations(["eps_surprise_pct"], as_of, security_id="JPM"))
    assert _dump(db.corporate_actions(ids, as_of)) == _dump(fx.corporate_actions(ids, as_of))


def test_latest_as_of_matches(stores):
    db, fx, _ = stores
    assert db.latest_as_of() == fx.latest_as_of()


def test_no_look_ahead(stores):
    db, _, ids = stores
    as_of = as_of_for_date(date(2023, 3, 10))
    p = db.prices(ids, as_of)
    assert p["trading_date"].max() == pd.Timestamp("2023-03-10")
    assert (p["available_at"] <= pd.Timestamp(as_of)).all()
    assert all(e.available_at <= as_of for e in db.events(as_of))
    # The 2023-03-22 FOMC outcome is not yet known on 2023-03-10: only the UPCOMING revision.
    fomc = {e.event_id: e for e in db.events(as_of)}["fomc-2023-03-22"]
    assert fomc.status == EventStatus.UPCOMING and fomc.actual_outcome is None
    # The synthetic stress event on 2023-03-13 is invisible the Friday before.
    assert "stress-2023-03-13" not in {e.event_id for e in db.events(as_of)}
    # Just before the bar's 16:15 availability the bar is not there.
    before_close = bar_available_at(date(2023, 3, 10)) - timedelta(minutes=1)
    assert db.prices(["JPM"], before_close)["trading_date"].max() == pd.Timestamp("2023-03-09")


def test_securities_from_sector_config(tmp_path):
    s = DuckDBStore(tmp_path / "x.duckdb")
    by = {x.security_id: x for x in s.securities()}
    assert set(by) == {"JPM", "BAC", "C", "MS", "GS", "SPY", "XLF", "CASH"}
    assert by["JPM"].role == SecurityRole.FOCAL
    assert by["SPY"].role == SecurityRole.BENCHMARK and not by["SPY"].investable
    assert by["CASH"].role == SecurityRole.DEFENSIVE
    assert s.securities("financials") and not s.securities("energy")


def _bar(d: date, close: float) -> PriceBar:
    return PriceBar(source_id="yahoo", origin=DataOrigin.REAL, available_at=bar_available_at(d),
                    availability_inferred=True, security_id="JPM", trading_date=d,
                    raw_close=close, volume=1e6)


def test_restatement_is_new_version_and_keeps_history(tmp_path):
    s = DuckDBStore(tmp_path / "r.duckdb")
    d1, d2 = date(2024, 1, 2), date(2024, 1, 3)
    first_fetch = datetime(2024, 1, 5, tzinfo=UTC)
    assert s.upsert_prices([_bar(d1, 100.0), _bar(d2, 101.0)], now=first_fetch) == 2
    # Same values again: nothing new is written.
    assert s.upsert_prices([_bar(d1, 100.0), _bar(d2, 101.0)], now=first_fetch) == 0
    # Re-fetch months later: Yahoo now says the 2024-01-03 close was 99.
    refetch = datetime(2024, 6, 1, 12, tzinfo=UTC)
    assert s.upsert_prices([_bar(d1, 100.0), _bar(d2, 99.0)], now=refetch) == 1

    early = as_of_for_date(date(2024, 2, 1))
    late = as_of_for_date(date(2024, 6, 2))
    p_early = s.prices(["JPM"], early).set_index("trading_date")["raw_close"]
    p_late = s.prices(["JPM"], late).set_index("trading_date")["raw_close"]
    assert p_early[pd.Timestamp(d2)] == 101.0  # earlier query unchanged
    assert p_late[pd.Timestamp(d2)] == 99.0
    assert len(s.prices(["JPM"], late)) == 2  # one row per date, never duplicated
    row = s.prices(["JPM"], late).iloc[1]
    assert row["available_at"] == pd.Timestamp(refetch)  # known only from the re-fetch
    with s._connect() as con:
        assert con.execute("SELECT count(*) FROM prices").fetchone()[0] == 3


def test_restated_dividend_does_not_change_earlier_adjustment(tmp_path):
    s = DuckDBStore(tmp_path / "d.duckdb")
    days = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    s.upsert_prices([_bar(d, 100.0) for d in days], now=datetime(2024, 1, 5, tzinfo=UTC))

    def div(v):
        return CorporateAction(source_id="yahoo", available_at=et(days[2], 9, 30),
                               security_id="JPM", ex_date=days[2],
                               kind=CorporateActionKind.DIVIDEND, value=v)

    s.upsert_corporate_actions([div(1.0)], now=datetime(2024, 1, 5, tzinfo=UTC))
    s.upsert_corporate_actions([div(2.0)], now=datetime(2024, 3, 1, tzinfo=UTC))
    a1 = s.prices(["JPM"], as_of_for_date(date(2024, 2, 1)))["adj_close"].iloc[0]
    a2 = s.prices(["JPM"], as_of_for_date(date(2024, 3, 2)))["adj_close"].iloc[0]
    assert a1 == pytest.approx(99.0)
    assert a2 == pytest.approx(98.0)


def test_event_and_observation_restatements(tmp_path):
    s = DuckDBStore(tmp_path / "e.duckdb")
    t0 = datetime(2024, 1, 10, tzinfo=UTC)
    base = {"source_id": "fomc", "event_id": "fomc-x", "event_class": EventClass.SCHEDULED,
            "subtype": "fomc_meeting", "title": "x", "scope": EventScope.MARKET,
            "status": EventStatus.OCCURRED, "revision": 1, "available_at": t0}
    s.upsert_events([Event(**base, actual_outcome="hold")], now=t0)
    s.upsert_events([Event(**base, actual_outcome="+25 bps")], now=t0 + timedelta(days=30))
    assert s.events(t0 + timedelta(days=1))[0].actual_outcome == "hold"
    assert s.events(t0 + timedelta(days=31))[0].actual_outcome == "+25 bps"

    def ob(v):
        return Observation(source_id="fred", available_at=t0, metric_id="DFF", economy="US",
                           period_end=date(2024, 1, 9), value=v, unit="percent")
    s.upsert_observations([ob(5.33)], now=t0)
    s.upsert_observations([ob(5.31)], now=t0 + timedelta(days=10))
    assert [o.value for o in s.observations(["DFF"], t0 + timedelta(days=1))] == [5.33]
    assert [o.value for o in s.observations(["DFF"], t0 + timedelta(days=11))] == [5.31]


def test_source_status_and_open_store(tmp_path):
    path = tmp_path / "s.duckdb"
    assert open_store(path) is None
    s = DuckDBStore(path)
    assert open_store(path) is None  # file exists but no prices yet
    now = datetime(2024, 1, 10, tzinfo=UTC)
    s.upsert_prices([_bar(date(2024, 1, 2), 100.0)], now=now)
    s.log_fetch("yahoo", now, "ok", 1, finished_at=now)
    s.log_fetch("fred", now, "error", 0, "boom", finished_at=now)
    s.log_fetch("edgar", now, "disabled", 0, "no UA", finished_at=now)
    st = {x.source_id: x for x in s.source_status(now=now + timedelta(days=1))}
    assert st["yahoo"].health == SourceHealth.FRESH and st["yahoo"].record_count == 1
    assert st["fred"].health == SourceHealth.ERROR and st["fred"].message == "boom"
    assert st["edgar"].health == SourceHealth.DISABLED
    assert st["fomc"].health == SourceHealth.MISSING
    stale = {x.source_id: x for x in s.source_status(now=now + timedelta(days=4))}
    assert stale["yahoo"].health == SourceHealth.STALE
    assert open_store(path) is not None
    assert open_store(path).latest_as_of() == bar_available_at(date(2024, 1, 2))
