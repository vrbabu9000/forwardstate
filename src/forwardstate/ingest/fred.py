"""FRED adapter: daily rate series from the public CSV endpoint (no API key).

D007 rule: an observation for date D is available at D + 1 business day, 16:00 New York
(inferred). FRED marks missing days with "."; those rows are skipped, never filled.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from datetime import date
from functools import partial

import pandas as pd

from forwardstate.contracts import DataOrigin, Observation
from forwardstate.pit import et

from .common import RawCache, SourceResult, retry

SRC = "fred"
SERIES = ["DFF", "DGS2", "DGS10", "DFEDTARU", "DFEDTARL"]
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"


def fred_available_at(d: date):
    return et((pd.Timestamp(d) + pd.offsets.BDay(1)).date(), 16, 0)


def parse_fred_csv(series: str, text: str, start: date) -> list[Observation]:
    df = pd.read_csv(io.StringIO(text))
    if df.shape[1] < 2:
        raise ValueError(f"FRED {series}: unexpected CSV header {list(df.columns)}")
    date_col = df.columns[0]  # 'observation_date' (new) or 'DATE' (old)
    val_col = series if series in df.columns else df.columns[1]
    vals = pd.to_numeric(df[val_col], errors="coerce")
    out: list[Observation] = []
    for ds, v in zip(df[date_col], vals):
        if pd.isna(v):
            continue
        d = pd.Timestamp(ds).date()
        if d < start:
            continue
        out.append(Observation(
            source_id=SRC, origin=DataOrigin.REAL, available_at=fred_available_at(d),
            availability_inferred=True, metric_id=series, economy="US", period_end=d,
            value=float(v), unit="percent",
        ))
    return out


def _default_get(url: str) -> str:  # pragma: no cover - network
    import requests

    r = requests.get(url, timeout=60, headers={"User-Agent": "forwardstate-data-fetch"})
    r.raise_for_status()
    return r.text


def fetch_fred(start: date, cache: RawCache, series: list[str] | None = None,
               get: Callable[[str], str] = _default_get,
               sleep: Callable[[float], None] | None = None) -> SourceResult:
    res = SourceResult(SRC)
    kw = {} if sleep is None else {"sleep": sleep}
    for s in series or SERIES:
        url = URL.format(series=s)
        try:
            txt = cache.text(SRC, f"{s}.csv", partial(
                retry, partial(get, url), what=f"fred {s}", is_empty=lambda t: not t.strip(),
                **kw))
            obs = parse_fred_csv(s, txt, start)
            res.observations += obs
            res.details[s] = {"rows": len(obs),
                              "first": str(obs[0].period_end) if obs else None,
                              "last": str(obs[-1].period_end) if obs else None}
        except Exception as exc:  # noqa: BLE001
            res.errors.append(f"{s}: {exc}")
    return res
