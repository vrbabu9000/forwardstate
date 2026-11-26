"""EventEngine: derived shocks, dedup links, event-study impacts and PIT windows."""

from __future__ import annotations

from datetime import date

import pandas as pd

from forwardstate.contracts import Confidence, DataOrigin, EventClass, EventScope
from forwardstate.events import EventEngine
from forwardstate.pit import as_of_for_date, bar_available_at
from forwardstate.services import EventService
from forwardstate.testing import FixtureStore, synthetic_as_of

BANKS = ["JPM", "BAC", "C", "MS", "GS"]


def _engine() -> EventEngine:
    return EventEngine(FixtureStore())


def test_protocol():
    assert isinstance(_engine(), EventService)


def test_synthetic_shock_detected_for_bac_c_and_sector():
    ev = _engine().list_events(synthetic_as_of(), event_classes=[EventClass.UNEXPECTED])
    ids = {e.event_id: e for e in ev}
    for sid in ("BAC", "C"):
        e = ids[f"shock-{sid}-2023-03-13"]
        assert e.origin == DataOrigin.DERIVED and e.subtype == "price_shock"
        assert e.scope == EventScope.FIRM and e.affected_security_ids == [sid]
        assert e.available_at == bar_available_at(date(2023, 3, 13))
        assert e.canonical_event_id == "stress-2023-03-13"  # EVT-04 link to stored event
    sector = ids["shock-sector-2023-03-13"]
    assert sector.scope == EventScope.SECTOR and sector.origin == DataOrigin.DERIVED
    assert "stress-2023-03-13" in ids  # stored event kept
    assert len(ids) == len(ev)  # deduplicated


def test_shock_not_visible_before_its_bar():
    eng = _engine()
    before = bar_available_at(date(2023, 3, 13)).replace(minute=14)
    assert not any(e.event_id.startswith("shock-") and "2023-03-13" in e.event_id
                   for e in eng.list_events(before))


def test_impact_realized_once_event_window_closes():
    store = FixtureStore()
    eng = EventEngine(store)
    dates = pd.DatetimeIndex(store.returns(["JPM"], synthetic_as_of()).index)
    t0 = int(dates.searchsorted(pd.Timestamp(date(2023, 4, 14))))
    eid = "earnings-JPM-2023-04-14"
    def at(k):
        return eng.impact_estimates(bar_available_at(dates[t0 + k].date()), event_id=eid,
                                    security_id="JPM")[0]

    pre, car_only, post = at(0), at(1), at(20)
    # CAR [-1, +1] is measurable once day +1 has closed; the drift only after day +20.
    assert pre.realized is False and pre.abnormal_return is None
    assert car_only.realized is True and car_only.abnormal_return is not None
    assert car_only.post_event_drift is None and "drift window still open" in car_only.note
    assert post.realized is True and post.abnormal_return is not None
    assert post.t_stat is not None and post.event_day_return is not None
    assert post.post_event_drift is not None and post.benchmark_id == "XLF"
    assert post.probability is None and "not proven causation" in post.note


def test_forward_estimate_from_history_and_peer_transmission():
    eng = _engine()
    t = as_of_for_date(date(2024, 10, 11))  # before JPM's Oct-2024 results
    est = eng.impact_estimates(t, event_id="earnings-JPM-2024-10-14")
    assert [e.security_id for e in est] == BANKS
    jpm = est[0]
    assert jpm.realized is False and jpm.sample_size == 10
    assert jpm.confidence == Confidence.MEDIUM and jpm.uncertainty is not None
    bac = est[1]
    assert bac.expected_return_impact is not None and "0.30" in bac.note


def test_forward_unavailable_with_little_history():
    eng = _engine()
    e = eng.impact_estimates(as_of_for_date(date(2022, 1, 10)), event_id="earnings-JPM-2022-01-14",
                             security_id="JPM")[0]
    assert e.confidence == Confidence.UNAVAILABLE and e.expected_return_impact is None


def test_sector_shock_impact_vs_spy_is_negative():
    est = _engine().impact_estimates(synthetic_as_of(), event_id="shock-sector-2023-03-13")
    assert all(e.realized and e.benchmark_id == "SPY" and e.abnormal_return < 0 for e in est)


def test_deterministic():
    a = [e.model_dump() for e in _engine().impact_estimates(synthetic_as_of(), security_id="C")]
    b = [e.model_dump() for e in _engine().impact_estimates(synthetic_as_of(), security_id="C")]
    assert a == b and len(a) > 10
