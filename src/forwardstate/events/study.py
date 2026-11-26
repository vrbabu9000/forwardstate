"""Market-model event study and rolling abnormal returns (EVT-02, FC-04).

Pure functions over numpy / pandas. No store access: callers pass returns that are already
cut to their as-of time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd

from forwardstate.pit import NY

# Event-study windows, in trading days relative to the event day (day 0).
EST_START, EST_END = -250, -11  # estimation window, inclusive
CAR_START, CAR_END = -1, 1  # event window -> CAR
DRIFT_START, DRIFT_END = 2, 20  # post-event drift
MIN_EST_OBS = 60  # fewer estimation days -> no estimate
MEDIUM_EST_OBS = 200  # this many -> MEDIUM confidence for a realized estimate
T_CRIT = 1.96  # |t| at or above this -> direction is significant

MARKET_CLOSE = time(16, 0)


def event_day(ts: datetime) -> date:
    """Calendar day whose close first reflects an event at ``ts``.

    Events strictly after the 16:00 New York close count from the next day.
    """
    local = ts.astimezone(NY)
    d = local.date()
    if local.time() > MARKET_CLOSE:
        d = d + timedelta(days=1)
    return d


def event_time(e) -> datetime:
    return e.occurred_at or e.scheduled_at or e.available_at


def day_index(dates: pd.DatetimeIndex, d: date) -> int | None:
    """Position of the first trading date on or after ``d``; None if beyond the data."""
    i = int(dates.searchsorted(pd.Timestamp(d), side="left"))
    return i if i < len(dates) else None


@dataclass(frozen=True)
class StudyResult:
    car: float
    event_day_return: float
    post_drift: float
    t_stat: float
    alpha: float
    beta: float
    sigma: float
    n_est: int


def market_model_study(y: np.ndarray, x: np.ndarray, t0: int) -> StudyResult | None:
    """Event study at index ``t0`` of security returns ``y`` against benchmark ``x``.

    The caller guarantees ``t0 + CAR_END < len(y)`` (event window closed); the drift is
    summed over whatever part of [+2, +20] exists and is only reported once it is complete. Returns None when
    the estimation window has fewer than ``MIN_EST_OBS`` valid joint days or the event-window
    returns are missing.
    """
    lo, hi = max(0, t0 + EST_START), t0 + EST_END + 1
    if hi <= lo or t0 + CAR_START < 0:
        return None
    ye, xe = y[lo:hi], x[lo:hi]
    ok = np.isfinite(ye) & np.isfinite(xe)
    n = int(ok.sum())
    if n < MIN_EST_OBS:
        return None
    ye, xe = ye[ok], xe[ok]
    vx = float(np.var(xe, ddof=1))
    if vx <= 0:
        return None
    beta = float(np.cov(xe, ye, ddof=1)[0, 1] / vx)
    alpha = float(ye.mean() - beta * xe.mean())
    resid = ye - alpha - beta * xe
    sigma = float(np.sqrt((resid**2).sum() / (n - 2)))
    ar = y - alpha - beta * x
    win = ar[t0 + CAR_START : t0 + CAR_END + 1]
    drift = ar[t0 + DRIFT_START : t0 + DRIFT_END + 1]
    if not np.all(np.isfinite(win)) or not np.isfinite(y[t0]):
        return None
    car = float(win.sum())
    t_stat = car / (sigma * np.sqrt(len(win))) if sigma > 0 else 0.0
    return StudyResult(
        car=car,
        event_day_return=float(y[t0]),
        post_drift=float(np.nansum(drift)),
        t_stat=float(t_stat),
        alpha=alpha,
        beta=beta,
        sigma=sigma,
        n_est=n,
    )


def rolling_abnormal(y: pd.Series, x: pd.Series, window: int = 60) -> pd.DataFrame:
    """Abnormal return of ``y`` vs ``x`` on each day, using a market model fitted on the
    ``window`` days *before* that day (never including it). Columns: ``ar, z, beta``."""
    df = pd.DataFrame({"y": y, "x": x})
    r = df.rolling(window, min_periods=window)
    mx, my = r["x"].mean(), r["y"].mean()
    vx, vy = r["x"].var(), r["y"].var()
    cxy = r["x"].cov(df["y"])
    beta = (cxy / vx).shift(1)
    alpha = (my - (cxy / vx) * mx).shift(1)
    resid_var = ((window - 1) / (window - 2) * (vy - cxy**2 / vx)).clip(lower=0).shift(1)
    ar = df["y"] - alpha - beta * df["x"]
    z = ar / np.sqrt(resid_var)
    return pd.DataFrame({"ar": ar, "z": z, "beta": beta})
