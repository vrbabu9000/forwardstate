"""Point-in-time feature snapshot."""

from __future__ import annotations

import math
from datetime import date

from forwardstate.features import FEATURE_COLUMNS, build_feature_snapshot
from forwardstate.pit import as_of_for_date
from forwardstate.testing import FixtureStore

IDS = ["JPM", "BAC", "C", "MS", "GS"]


def test_snapshot_shape_and_values():
    store = FixtureStore()
    sid, df = build_feature_snapshot(store, as_of_for_date(date(2024, 6, 28)), IDS)
    assert list(df.columns) == FEATURE_COLUMNS and list(df.index) == IDS
    assert len(sid) == 64
    row = df.loc["JPM"]
    for col in ["ret_21d", "ret_63d", "ret_252d", "vol_63d", "beta_spy", "beta_xlf",
                "rate_sensitivity", "analyst_target_gap", "last_earnings_surprise_pct"]:
        assert math.isfinite(row[col]), col
    assert 0.7 < row["beta_spy"] < 1.4  # synthetic JPM beta is 1.05
    assert row["days_to_next_earnings"] > 0  # Q3 results (mid-July) known 30 days ahead


def test_snapshot_deterministic_and_pit():
    store = FixtureStore()
    t = as_of_for_date(date(2023, 3, 10))
    a, _ = build_feature_snapshot(store, t, IDS)
    b, _ = build_feature_snapshot(store, t, IDS)
    assert a == b
    later, _ = build_feature_snapshot(store, as_of_for_date(date(2023, 3, 13)), IDS)
    assert later != a


def test_missing_history_is_nan_not_invented():
    _, df = build_feature_snapshot(FixtureStore(), as_of_for_date(date(2022, 1, 20)), ["JPM"])
    assert math.isnan(df.loc["JPM", "ret_252d"]) and math.isnan(df.loc["JPM", "beta_spy"])
