"""Point-in-time feature snapshot: one row per security, built only from data known by ``as_of``."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from forwardstate.contracts import EventClass, stable_hash
from forwardstate.pit import NY, ensure_utc, trading_days_between

MARKET_ID, SECTOR_ID = "SPY", "XLF"
RATE_METRIC = "DGS2"
BETA_WINDOW = 252
VOL_WINDOW = 63
RATE_WINDOW = 756  # ~3 years of daily data for the rate-sensitivity regression
MIN_REG_OBS = 60
ANALYST_LOOKBACK_DAYS = 365

FEATURE_COLUMNS = [
    "history_days",
    "last_price",
    "ret_21d",
    "ret_63d",
    "ret_252d",
    "vol_63d",
    "beta_spy",
    "beta_xlf",
    "rate_sensitivity",
    "rate_sensitivity_t",
    "rate_sensitivity_n",
    "analyst_target_gap",
    "analyst_count",
    "days_to_next_earnings",
    "last_earnings_surprise_pct",
]
"""Column meanings (all decimals unless noted):

- ``history_days``: daily returns available as of the snapshot;
- ``ret_Nd``: trailing N-trading-day price return from adjusted closes;
- ``vol_63d``: annualised std. dev. of the last 63 daily returns (x sqrt(252));
- ``beta_spy`` / ``beta_xlf``: OLS beta of daily returns on the benchmark, last 252 days;
- ``rate_sensitivity``: slope of daily return on the daily DGS2 change, per 1 percentage point
  (100 bps); ``_t`` is its t-stat and ``_n`` the observation count (last 756 days);
- ``analyst_target_gap``: mean of each analyst firm's latest target issued in the last 365 days,
  divided by the latest raw close, minus 1;
- ``days_to_next_earnings``: weekdays to the next *known* scheduled quarterly results;
- ``last_earnings_surprise_pct``: latest ``eps_surprise_pct`` observation, percent.
"""


def _ols(y: np.ndarray, x: np.ndarray) -> tuple[float, float, int]:
    ok = np.isfinite(y) & np.isfinite(x)
    y, x = y[ok], x[ok]
    n = len(y)
    if n < MIN_REG_OBS:
        return math.nan, math.nan, n
    xm = x - x.mean()
    sxx = float((xm**2).sum())
    if sxx <= 0:
        return math.nan, math.nan, n
    b = float((xm * (y - y.mean())).sum() / sxx)
    a = float(y.mean() - b * x.mean())
    resid = y - a - b * x
    se = math.sqrt(float((resid**2).sum()) / (n - 2) / sxx)
    return b, (b / se if se > 0 else math.nan), n


def _trailing(r: pd.Series, n: int) -> float:
    r = r.dropna()
    if len(r) < n:
        return math.nan
    return float(np.prod(1 + r.iloc[-n:].to_numpy()) - 1)


def _clean(v):
    if v is None:
        return None
    v = float(v)
    return None if not math.isfinite(v) else round(v, 12)


def build_feature_snapshot(
    store, as_of: datetime, security_ids: list[str]
) -> tuple[str, pd.DataFrame]:
    """Return ``(snapshot_id, features)``; ``features`` is indexed by security_id with
    ``FEATURE_COLUMNS``. Missing inputs give NaN, never a made-up value."""
    as_of = ensure_utc(as_of)
    ids = [s for s in security_ids]
    fetch = list(dict.fromkeys(ids + [MARKET_ID, SECTOR_ID]))
    prices = store.prices(fetch, as_of)
    rets = store.returns(fetch, as_of)
    last_raw = prices.groupby("security_id")["raw_close"].last() if len(prices) else pd.Series()

    rate = store.observations([RATE_METRIC], as_of)
    if rate:
        dgs2 = pd.Series({pd.Timestamp(o.period_end): o.value for o in rate}).sort_index()
        dgs2_chg = dgs2.diff()
    else:
        dgs2_chg = pd.Series(dtype=float)

    analysts = store.analyst_observations(as_of, ids)
    events = store.events(as_of, ids, [EventClass.SCHEDULED])
    rows = []
    for sid in ids:
        r = rets[sid] if sid in rets.columns else pd.Series(dtype=float)
        row = dict.fromkeys(FEATURE_COLUMNS, math.nan)
        row["history_days"] = int(r.notna().sum())
        row["last_price"] = float(last_raw.get(sid, math.nan))
        row["ret_21d"] = _trailing(r, 21)
        row["ret_63d"] = _trailing(r, 63)
        row["ret_252d"] = _trailing(r, 252)
        rv = r.dropna()
        if len(rv) >= VOL_WINDOW:
            row["vol_63d"] = float(rv.iloc[-VOL_WINDOW:].std(ddof=1) * math.sqrt(252))
        for bm, col in ((MARKET_ID, "beta_spy"), (SECTOR_ID, "beta_xlf")):
            if bm in rets.columns and sid in rets.columns:
                j = rets[[sid, bm]].dropna().iloc[-BETA_WINDOW:]
                if sid == bm:
                    row[col] = 1.0 if len(j) >= MIN_REG_OBS else math.nan
                else:
                    row[col] = _ols(j[sid].to_numpy(), j[bm].to_numpy())[0]
        if len(dgs2_chg) and len(rv):
            j = pd.concat([rv.rename("r"), dgs2_chg.rename("d")], axis=1, join="inner").dropna()
            j = j.iloc[-RATE_WINDOW:]
            b, t, n = _ols(j["r"].to_numpy(), j["d"].to_numpy())
            row["rate_sensitivity"], row["rate_sensitivity_t"], row["rate_sensitivity_n"] = b, t, n

        cutoff = as_of - timedelta(days=ANALYST_LOOKBACK_DAYS)
        latest: dict[str, float] = {}
        for o in analysts:  # sorted by issued_at, so the last write per firm wins
            if o.security_id == sid and o.target_price and o.issued_at >= cutoff:
                latest[o.analyst_source] = o.target_price
        row["analyst_count"] = len(latest)
        if latest and math.isfinite(row["last_price"]) and row["last_price"] > 0:
            row["analyst_target_gap"] = float(np.mean(list(latest.values())) / row["last_price"] - 1)

        nxt = [e.scheduled_at for e in events
               if e.subtype == "quarterly_results" and sid in e.affected_security_ids
               and e.scheduled_at is not None and e.scheduled_at > as_of]
        if nxt:
            row["days_to_next_earnings"] = trading_days_between(as_of.astimezone(NY).date(), min(nxt).astimezone(NY).date())
        surpr = store.observations(["eps_surprise_pct"], as_of, security_id=sid)
        if surpr:
            last = max(surpr, key=lambda o: (o.available_at, o.period_end))
            row["last_earnings_surprise_pct"] = float(last.value)
        rows.append(row)

    df = pd.DataFrame(rows, index=pd.Index(ids, name="security_id"), columns=FEATURE_COLUMNS)
    payload = {
        "columns": FEATURE_COLUMNS,
        "rows": {sid: [_clean(v) for v in df.loc[sid].tolist()] for sid in ids},
    }
    return stable_hash(payload), df
