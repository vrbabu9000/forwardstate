"""Source adapters map mocked payloads correctly. No network is used."""

from __future__ import annotations

import json
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from forwardstate.contracts import (
    AnalystAction,
    CorporateActionKind,
    DataOrigin,
    EventClass,
    EventScope,
    EventStatus,
    Observation,
)
from forwardstate.ingest import edgar, fomc, fred, yahoo
from forwardstate.ingest.common import RawCache, retry
from forwardstate.ingest.fetch import run_fetch
from forwardstate.pit import NY, UTC, bar_available_at, et
from forwardstate.storage import DuckDBStore

NOW = datetime(2026, 11, 26, 12, tzinfo=UTC)
START = date(2015, 1, 1)


def no_sleep(_s: float) -> None:
    pass


# ---- Yahoo: bars and split un-adjustment -------------------------------------------------
def _hist() -> pd.DataFrame:
    """Yahoo-style frame: Close is split-adjusted. True raw closes are 200, 202, 101, 102, 52."""
    idx = pd.DatetimeIndex(["2020-06-01", "2020-06-02", "2020-06-03", "2020-06-04",
                            "2020-06-05"]).tz_localize(NY)
    return pd.DataFrame({
        "Open": [25.0, 25.25, 50.5, 51.0, 52.0],
        "High": [26.0, 26.0, 51.0, 52.0, 53.0],
        "Low": [24.0, 25.0, 50.0, 50.0, 51.0],
        "Close": [25.0, 25.25, 50.5, 51.0, 52.0],
        "Adj Close": [24.0, 24.2, 49.0, 50.0, 52.0],
        "Volume": [800.0, 800.0, 400.0, 400.0, 100.0],
        "Dividends": [0.0, 0.0, 0.0, 0.25, 0.0],  # Yahoo shows it split-adjusted
        "Stock Splits": [0.0, 0.0, 2.0, 0.0, 2.0],
    }, index=idx)


def test_split_factors():
    f = yahoo.split_factors(_hist()["Stock Splits"])
    assert list(f) == [4.0, 4.0, 2.0, 2.0, 1.0]


def test_split_unadjustment_rebuilds_raw_close():
    bars, acts = yahoo.map_history("XYZ", _hist(), START, NOW)
    assert [b.raw_close for b in bars] == [100.0, 101.0, 101.0, 102.0, 52.0]
    assert [b.volume for b in bars] == [200.0, 200.0, 200.0, 200.0, 100.0]
    assert bars[0].open == 100.0 and bars[0].high == 104.0
    b = bars[0]
    assert b.origin == DataOrigin.REAL and b.availability_inferred
    assert b.available_at == bar_available_at(date(2020, 6, 1))
    splits = [a for a in acts if a.kind == CorporateActionKind.SPLIT]
    divs = [a for a in acts if a.kind == CorporateActionKind.DIVIDEND]
    assert [(a.ex_date, a.value) for a in splits] == [(date(2020, 6, 3), 2.0),
                                                     (date(2020, 6, 5), 2.0)]
    assert divs[0].value == pytest.approx(0.5)  # 0.25 shown, one later 2:1 split -> 0.50 raw
    assert divs[0].available_at == et(date(2020, 6, 4), 9, 30) and divs[0].availability_inferred


def test_split_adjusted_series_is_continuous_after_pit_adjustment():
    from forwardstate.pit import adjust_closes

    bars, acts = yahoo.map_history("XYZ", _hist(), START, NOW)
    splits = [a for a in acts if a.kind == CorporateActionKind.SPLIT]
    f = pd.DataFrame({"security_id": "XYZ", "trading_date": [b.trading_date for b in bars],
                      "raw_close": [b.raw_close for b in bars]})
    adj = adjust_closes(f, splits, NOW)
    assert list(adj) == list(_hist()["Close"])  # matches Yahoo split-adjusted Close
    # Before the second split is known, only the first split is applied.
    early = adjust_closes(f, splits, et(date(2020, 6, 4), 23, 59))
    assert list(early[:4]) == [50.0, 50.5, 101.0, 102.0]


def test_incomplete_bar_is_dropped():
    h = _hist()
    fetched = et(date(2020, 6, 5), 12, 0)  # during the trading day
    bars, _ = yahoo.map_history("XYZ", h, START, fetched)
    assert bars[-1].trading_date == date(2020, 6, 4)


# ---- Yahoo: earnings and analyst ----------------------------------------------------------
def _earnings() -> pd.DataFrame:
    idx = pd.DatetimeIndex(["2027-01-14 08:00", "2026-10-13 06:00",
                            "2026-07-14 06:00"]).tz_localize(NY)
    idx.name = "Earnings Date"
    return pd.DataFrame({"EPS Estimate": [5.86, 5.94, 5.80],
                         "Reported EPS": [np.nan, 5.75, 6.14],
                         "Surprise(%)": [np.nan, -3.24, 5.86]}, index=idx)


def test_map_earnings():
    events, obs = yahoo.map_earnings("JPM", _earnings(), START, NOW)
    by = {(e.event_id, e.revision): e for e in events}
    up = by[("earnings-JPM-2026-10-13", 0)]
    occ = by[("earnings-JPM-2026-10-13", 1)]
    when = et(date(2026, 10, 13), 6, 0)
    assert up.status == EventStatus.UPCOMING and up.subtype == "quarterly_results"
    assert up.available_at == when - pd.Timedelta(days=30) and up.availability_inferred
    assert up.expected_outcome is None  # the final consensus is not known 30 days early
    assert occ.status == EventStatus.OCCURRED and occ.available_at == when
    assert occ.surprise == pytest.approx(-0.0324)
    assert "5.75" in occ.actual_outcome and "5.94" in occ.actual_outcome
    assert ("earnings-JPM-2027-01-14", 1) not in by  # future: upcoming only
    assert ("earnings-JPM-2027-01-14", 0) in by
    m = {(o.metric_id, o.period_end): o.value for o in obs}
    assert m[("eps_actual", date(2026, 9, 30))] == 5.75
    assert m[("eps_estimate", date(2026, 9, 30))] == 5.94
    assert m[("eps_surprise_pct", date(2026, 6, 30))] == pytest.approx(5.86)
    assert all(o.available_at >= et(date(2026, 7, 14), 6, 0) for o in obs)


def test_map_upgrades_downgrades():
    idx = pd.DatetimeIndex(["2026-11-02 21:58:18", "2026-10-14 13:53:14", "2026-10-14 13:53:14",
                            "2010-01-01"], name="GradeDate")
    df = pd.DataFrame({
        "Firm": ["UBS", "Barclays", "Barclays", "Old"],
        "ToGrade": ["Buy", "Overweight", "Overweight", "Buy"],
        "FromGrade": ["Neutral", "Overweight", "", "Buy"],
        "Action": ["up", "main", "reit", "init"],
        "priceTargetAction": ["Raises", "Raises", "Maintains", ""],
        "currentPriceTarget": [400.0, 420.0, 420.0, 0.0],
        "priorPriceTarget": [395.0, 410.0, 0.0, 0.0],
    }, index=idx)
    out = yahoo.map_upgrades_downgrades("JPM", df, START)
    assert len(out) == 3  # 2010 row is before start
    ubs = next(o for o in out if o.analyst_source == "UBS")
    assert ubs.action == AnalystAction.UPGRADE and ubs.from_rating == "Neutral"
    assert ubs.target_price == 400.0 and ubs.prior_target_price == 395.0
    assert ubs.available_at == et(date(2026, 11, 2), 23, 59) and ubs.availability_inferred
    assert ubs.issued_at <= ubs.available_at
    bar = sorted((o for o in out if o.analyst_source == "Barclays"), key=lambda o: o.action.value)
    assert {o.action for o in bar} == {AnalystAction.TARGET_CHANGE, AnalystAction.MAINTAIN}
    assert len({o.observation_id for o in out}) == 3
    assert next(o for o in bar if o.action == AnalystAction.MAINTAIN).from_rating is None


class _FakeTicker:
    def __init__(self, sym: str, fail: bool = False):
        self.sym, self.fail, self.calls = sym, fail, 0

    def history(self, **kw):
        self.calls += 1
        if self.fail:
            raise RuntimeError("Too Many Requests. Rate limited.")
        if self.calls == 1:
            return pd.DataFrame()  # soft rate limit: empty frame, retried
        return _hist()

    def get_earnings_dates(self, limit=12):
        return _earnings()

    @property
    def upgrades_downgrades(self):
        return pd.DataFrame()


def test_fetch_yahoo_retries_and_continues_per_ticker(tmp_path):
    fakes = {"JPM": _FakeTicker("JPM"), "BAC": _FakeTicker("BAC", fail=True),
             "SPY": _FakeTicker("SPY")}
    res = yahoo.fetch_yahoo(["JPM", "BAC", "SPY"], START, RawCache(tmp_path), NOW,
                            ticker_factory=fakes.__getitem__, sleep=no_sleep)
    assert res.details["JPM"]["bars"] == 5 and res.details["SPY"]["bars"] == 5
    assert res.details["BAC"]["bars"] == 0
    assert any("BAC history" in e for e in res.errors)
    assert fakes["JPM"].calls == 2 and fakes["BAC"].calls == 4
    assert all(e.affected_security_ids != ["SPY"] for e in res.events)  # ETFs: no earnings
    # Second run is served from data/cache: no new calls.
    yahoo.fetch_yahoo(["JPM"], START, RawCache(tmp_path), NOW,
                      ticker_factory=fakes.__getitem__, sleep=no_sleep)
    assert fakes["JPM"].calls == 2


def test_retry_gives_up():
    calls = []

    def boom():
        calls.append(1)
        raise ValueError("x")

    with pytest.raises(ValueError):
        retry(boom, what="t", attempts=3, sleep=no_sleep)
    assert len(calls) == 3


# ---- FRED --------------------------------------------------------------------------------
FRED_CSV = "observation_date,DFF\n2014-12-31,0.06\n2024-01-05,5.33\n2024-01-08,.\n2024-01-09,5.33\n"


def test_parse_fred_csv():
    obs = fred.parse_fred_csv("DFF", FRED_CSV, START)
    assert [o.period_end for o in obs] == [date(2024, 1, 5), date(2024, 1, 9)]  # '.' skipped
    o = obs[0]
    assert o.metric_id == "DFF" and o.unit == "percent" and o.value == 5.33
    assert o.availability_inferred and o.origin == DataOrigin.REAL
    assert o.available_at == et(date(2024, 1, 8), 16, 0)  # Friday + 1 business day = Monday
    assert fred.parse_fred_csv("DGS2", "DATE,DGS2\n2024-01-02,4.33\n", START)[0].value == 4.33


def test_fetch_fred_uses_cache(tmp_path):
    calls = []

    def get(url):
        calls.append(url)
        return FRED_CSV.replace("DFF", url.split("=")[-1])

    r = fred.fetch_fred(START, RawCache(tmp_path), get=get, sleep=no_sleep)
    assert len(calls) == 5 and not r.errors
    assert {o.metric_id for o in r.observations} == set(fred.SERIES)
    fred.fetch_fred(START, RawCache(tmp_path), get=get, sleep=no_sleep)
    assert len(calls) == 5


# ---- FOMC --------------------------------------------------------------------------------
def _upper(points: list[tuple[str, float]]) -> list[Observation]:
    return [Observation(source_id="fred", available_at=et(date.fromisoformat(d), 16, 0),
                        metric_id="DFEDTARU", period_end=date.fromisoformat(d), value=v,
                        unit="percent") for d, v in points]


def test_target_change():
    up = _upper([("2022-03-15", 0.25), ("2022-03-16", 0.25), ("2022-03-17", 0.50)])
    assert fomc.target_change_bps(date(2022, 3, 16), up) == 25
    assert fomc.outcome_text(25) == "+25 bps" and fomc.outcome_text(0) == "hold"
    assert fomc.outcome_text(-50) == "-50 bps"
    assert fomc.target_change_bps(date(2030, 1, 1), up) is None


def test_build_fomc_events():
    up = _upper([("2020-03-02", 1.75), ("2020-03-04", 1.25), ("2020-03-16", 0.25),
                 ("2022-03-15", 0.25), ("2022-03-17", 0.50)])
    res = fomc.build_fomc_events(up, now=NOW, start=START)
    by = {(e.event_id, e.revision): e for e in res.events}
    occ = by[("fomc-2022-03-16", 1)]
    assert occ.actual_outcome == "+25 bps" and occ.occurred_at == et(date(2022, 3, 16), 14, 0)
    assert occ.scope == EventScope.MARKET and occ.event_class == EventClass.SCHEDULED
    assert set(occ.affected_security_ids) == {"JPM", "BAC", "C", "MS", "GS"}
    upc = by[("fomc-2022-03-16", 0)]
    assert upc.status == EventStatus.UPCOMING
    assert upc.available_at == et(date(2022, 3, 16), 14, 0) - pd.Timedelta(days=60)
    # Future meeting: UPCOMING only. Past meeting without rate data: empty outcome.
    assert ("fomc-2026-12-09", 0) in by and ("fomc-2026-12-09", 1) not in by
    assert by[("fomc-2015-01-28", 1)].actual_outcome is None
    # Unscheduled: no UPCOMING revision (it was not known ahead), class UNEXPECTED.
    em = [e for e in res.events if e.event_id == "fomc-2020-03-03"]
    assert len(em) == 1 and em[0].event_class == EventClass.UNEXPECTED
    assert em[0].actual_outcome == "-50 bps"
    assert by[("fomc-2020-03-15", 0)].actual_outcome == "-100 bps"
    assert ("fomc-2020-03-18", 0) not in by  # cancelled meeting


def test_fomc_config_covers_2015_to_2026():
    scheduled, unscheduled = fomc.load_fomc_config()
    years = {d.year for d in scheduled}
    assert years == set(range(2015, 2027))
    assert all(sum(d.year == y for d in scheduled) == (7 if y == 2020 else 8) for y in years)
    assert len(unscheduled) == 2


# ---- EDGAR -------------------------------------------------------------------------------
SUBMISSIONS = {
    "cik": "19617",
    "filings": {
        "recent": {
            "accessionNumber": ["0000019617-24-000500", "0000019617-24-000400",
                                "0000019617-24-000300", "0000019617-24-000200"],
            "filingDate": ["2024-10-11", "2024-11-01", "2024-10-10", "2024-09-01"],
            "reportDate": ["2024-10-11", "2024-09-30", "", ""],
            "acceptanceDateTime": ["2024-10-11T06:47:31.000Z", "2024-11-01T16:05:00.000Z",
                                   "2024-10-10T10:00:00.000Z", "2024-09-01T10:00:00.000Z"],
            "form": ["8-K", "10-Q", "424B2", "10-K"],
            "items": ["2.02,9.01", "", "", ""],
            "primaryDocument": ["a.htm", "b.htm", "c.htm", "d.htm"],
        },
        "files": [{"name": "CIK0000019617-submissions-001.json", "filingFrom": "2010-01-01",
                   "filingTo": "2014-06-30"}],
    },
}


def test_edgar_disabled_without_user_agent(tmp_path):
    called = []
    r = edgar.fetch_edgar(["JPM"], START, RawCache(tmp_path),
                          get=lambda u, ua: called.append(u), env={})
    assert r.disabled and edgar.ENV_UA in r.disabled and not called and not r.events


def test_edgar_maps_filings(tmp_path):
    seen = []

    def get(url, ua):
        seen.append((url, ua))
        return json.dumps(SUBMISSIONS)

    r = edgar.fetch_edgar(["JPM", "SPY"], START, RawCache(tmp_path), get=get,
                          env={edgar.ENV_UA: "TestApp test@example.invalid"},
                          throttle=edgar.Throttle(1e9))
    assert len(seen) == 1  # extra file ends before start; SPY has no CIK
    assert seen[0][0].endswith("CIK0000019617.json") and seen[0][1].startswith("TestApp")
    by = {e.event_id: e for e in r.events}
    assert set(by) == {"edgar-0000019617-24-000500", "edgar-0000019617-24-000400",
                       "edgar-0000019617-24-000200"}  # 424B2 skipped
    k8 = by["edgar-0000019617-24-000500"]
    assert k8.subtype == "filing_8k" and k8.event_class == EventClass.UNEXPECTED
    assert k8.scope == EventScope.FIRM and k8.affected_security_ids == ["JPM"]
    assert k8.available_at == et(date(2024, 10, 11), 6, 47) + pd.Timedelta(seconds=31)
    assert "2.02" in k8.title
    assert by["edgar-0000019617-24-000400"].subtype == "filing_10q"
    assert by["edgar-0000019617-24-000200"].event_class == EventClass.SCHEDULED


def test_throttle_limits_rate():
    t = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        t[0] += s

    th = edgar.Throttle(10, clock=lambda: t[0], sleep=sleep)
    for _ in range(5):
        th.wait()
    assert t[0] == pytest.approx(0.4)


# ---- run_fetch end to end (mocked adapters) ------------------------------------------------
def test_run_fetch_end_to_end(tmp_path, monkeypatch):
    monkeypatch.delenv(edgar.ENV_UA, raising=False)
    db = tmp_path / "fs.duckdb"
    fakes = {t: _FakeTicker(t) for t in ["JPM", "SPY"]}

    def fred_get(url):
        s = url.split("=")[-1]
        return f"observation_date,{s}\n2022-03-15,0.25\n2022-03-17,0.50\n"

    adapters = {
        "yahoo": lambda: yahoo.fetch_yahoo(["JPM", "SPY"], START, RawCache(tmp_path / "c"), NOW,
                                           ticker_factory=fakes.__getitem__, sleep=no_sleep),
        "fred": lambda: fred.fetch_fred(START, RawCache(tmp_path / "c"), get=fred_get),
    }
    lines: list[str] = []
    rc = run_fetch("2015-01-01", "all", "JPM,SPY", db_path=db, cache_dir=tmp_path / "c",
                   now=NOW, adapters=adapters, out=lines.append)
    assert rc == 0, lines
    s = DuckDBStore(db)
    assert len(s.prices(["JPM", "SPY"], NOW)) == 10
    st = {x.source_id: x.health.value for x in s.source_status(now=NOW)}
    assert st == {"yahoo": "fresh", "fred": "fresh", "fomc": "fresh", "edgar": "disabled"}
    ev = {e.event_id: e for e in s.events(NOW)}
    assert ev["fomc-2022-03-16"].actual_outcome == "+25 bps"
    assert any("DISABLED" in x for x in lines)
    # A second run writes no new versions.
    run_fetch("2015-01-01", "all", "JPM,SPY", db_path=db, cache_dir=tmp_path / "c", now=NOW,
              adapters=adapters, out=lines.append)
    with s._connect() as con:
        assert con.execute("SELECT max(version) FROM prices").fetchone()[0] == 0
