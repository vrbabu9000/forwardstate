from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from forwardstate.contracts import Constraints, Holding, Portfolio, stable_hash
from forwardstate.pit import adjust_closes, as_of_for_date, bar_available_at
from forwardstate.services import PointInTimeStore
from forwardstate.testing import FixtureStore, build_synthetic_dataset


def test_no_shorting_or_leverage():
    with pytest.raises(ValidationError):
        Constraints(long_only=False)
    with pytest.raises(ValidationError):
        Constraints(allow_leverage=True)
    with pytest.raises(ValidationError):
        Holding(security_id="JPM", weight=-0.1)


def test_stable_hash_is_deterministic():
    p = Portfolio(total_value=1000, holdings=[Holding(security_id="JPM", weight=1.0)])
    assert stable_hash(p) == stable_hash(Portfolio.model_validate(p.model_dump()))
    assert stable_hash({"b": 1, "a": 2}) == stable_hash({"a": 2, "b": 1})


def test_fixture_is_labelled_synthetic():
    ds = build_synthetic_dataset()
    assert all(b.origin.value == "synthetic" for b in ds.bars)
    assert all(e.origin.value == "synthetic" for e in ds.events)


def test_fixture_store_is_point_in_time():
    store = FixtureStore()
    assert isinstance(store, PointInTimeStore)
    as_of = as_of_for_date(date(2023, 3, 10))
    prices = store.prices(["JPM"], as_of)
    assert prices["trading_date"].max().date() == date(2023, 3, 10)
    assert (prices["available_at"] <= as_of).all()
    for e in store.events(as_of):
        assert e.available_at <= as_of
    # an FOMC meeting after as_of is visible only as 'upcoming' with no outcome
    later = [e for e in store.events(as_of) if e.event_id == "fomc-2023-03-22"]
    assert later and later[0].status.value == "upcoming" and later[0].actual_outcome is None


def test_adjustment_uses_only_known_actions():
    store = FixtureStore()
    early = store.prices(["JPM"], as_of_for_date(date(2022, 3, 1)))
    late = store.prices(["JPM"], as_of_for_date(date(2024, 12, 31)))
    first_raw = early["raw_close"].iloc[0]
    assert early["adj_close"].iloc[0] < first_raw  # Jan-2022 dividend known by March
    assert late["adj_close"].iloc[0] < early["adj_close"].iloc[0]  # more dividends known later
    assert adjust_closes(early.head(0), [], as_of_for_date(date(2022, 3, 1))).empty


def test_bar_availability_is_after_close():
    t = bar_available_at(date(2024, 7, 1))
    assert t == datetime(2024, 7, 1, 20, 15, tzinfo=timezone.utc)  # 16:15 EDT
