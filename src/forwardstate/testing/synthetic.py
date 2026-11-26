"""Deterministic SYNTHETIC dataset for tests and the offline demo. Owned by the integrator.

Every record is labelled ``origin=SYNTHETIC`` and ``source_id='synthetic'``. Prices are
simulated and are NOT real market history. FOMC meeting dates follow the real 2022–2024
calendar so event logic can be exercised realistically; their outcomes here are illustrative.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

from forwardstate.contracts import (
    AnalystAction,
    AnalystObservation,
    CorporateAction,
    CorporateActionKind,
    DataOrigin,
    Event,
    EventClass,
    EventScope,
    EventStatus,
    Observation,
    PriceBar,
    Security,
    SecurityRole,
)
from forwardstate.pit import bar_available_at, end_of_day_utc, et

SRC = "synthetic"
SYN = DataOrigin.SYNTHETIC
START = date(2022, 1, 3)
END = date(2024, 12, 31)
SHOCK_DATE = date(2023, 3, 13)  # synthetic sector stress day

BANKS = {
    "JPM": ("JPMorgan Chase", SecurityRole.FOCAL, 150.0, 1.05),
    "BAC": ("Bank of America", SecurityRole.PEER, 40.0, 1.20),
    "C": ("Citigroup", SecurityRole.PEER, 60.0, 1.25),
    "MS": ("Morgan Stanley", SecurityRole.PEER, 90.0, 1.15),
    "GS": ("Goldman Sachs", SecurityRole.PEER, 350.0, 1.10),
}
BENCHMARKS = {"SPY": ("SPDR S&P 500 ETF", 450.0), "XLF": ("Financial Select Sector SPDR", 35.0)}

# Real FOMC statement dates 2022-2024; decisions in bps (illustrative here, labelled synthetic).
FOMC = [
    (date(2022, 1, 26), 0),
    (date(2022, 3, 16), 25),
    (date(2022, 5, 4), 50),
    (date(2022, 6, 15), 75),
    (date(2022, 7, 27), 75),
    (date(2022, 9, 21), 75),
    (date(2022, 11, 2), 75),
    (date(2022, 12, 14), 50),
    (date(2023, 2, 1), 25),
    (date(2023, 3, 22), 25),
    (date(2023, 5, 3), 25),
    (date(2023, 6, 14), 0),
    (date(2023, 7, 26), 25),
    (date(2023, 9, 20), 0),
    (date(2023, 11, 1), 0),
    (date(2023, 12, 13), 0),
    (date(2024, 1, 31), 0),
    (date(2024, 3, 20), 0),
    (date(2024, 5, 1), 0),
    (date(2024, 6, 12), 0),
    (date(2024, 7, 31), 0),
    (date(2024, 9, 18), -50),
    (date(2024, 11, 7), -25),
    (date(2024, 12, 18), -25),
]


@dataclass
class SyntheticDataset:
    securities: list[Security]
    bars: list[PriceBar]
    actions: list[CorporateAction]
    observations: list[Observation]
    events: list[Event]
    analyst: list[AnalystObservation]
    trading_days: list[date] = field(default_factory=list)


def _securities() -> list[Security]:
    secs = [
        Security(security_id=t, ticker=t, name=n, sector="financials", role=r)
        for t, (n, r, _, _) in BANKS.items()
    ]
    secs += [
        Security(
            security_id=t,
            ticker=t,
            name=n,
            sector="financials",
            role=SecurityRole.BENCHMARK,
            investable=False,
        )
        for t, (n, _) in BENCHMARKS.items()
    ]
    secs.append(
        Security(
            security_id="CASH",
            ticker="CASH",
            name="Cash / liquid equivalents",
            sector="financials",
            role=SecurityRole.DEFENSIVE,
        )
    )
    return secs


def _nearest_bday(d: date, days: list[date]) -> date:
    for x in days:
        if x >= d:
            return x
    return days[-1]


@lru_cache(maxsize=4)
def build_synthetic_dataset(seed: int = 7) -> SyntheticDataset:
    rng = np.random.default_rng(seed)
    days = [d.date() for d in pd.bdate_range(START, END)]
    n = len(days)
    shock_i = days.index(SHOCK_DATE)

    market = rng.normal(0.0003, 0.010, n)
    sector = rng.normal(0.0, 0.006, n)
    sector[shock_i] -= 0.06  # synthetic sector stress
    sector[shock_i + 1 : shock_i + 4] += 0.012  # partial rebound

    rets: dict[str, np.ndarray] = {}
    rets["SPY"] = market
    rets["XLF"] = 1.05 * market + sector
    for t, (_, _, _, beta) in BANKS.items():
        idio = rng.normal(0.0, 0.008, n)
        r = beta * market + sector + idio
        if t == "BAC":
            r[shock_i] -= 0.04
        if t == "C":
            r[shock_i] -= 0.03
        rets[t] = r

    starts = {t: v[2] for t, v in BANKS.items()} | {t: v[1] for t, v in BENCHMARKS.items()}
    bars: list[PriceBar] = []
    actions: list[CorporateAction] = []
    for t, r in rets.items():
        price = starts[t] * np.cumprod(1 + r)
        for i, d in enumerate(days):
            bars.append(
                PriceBar(
                    source_id=SRC,
                    origin=SYN,
                    available_at=bar_available_at(d),
                    security_id=t,
                    trading_date=d,
                    raw_close=round(float(price[i]), 4),
                    volume=float(rng.integers(5_000_000, 30_000_000)),
                )
            )
        if (
            t in BANKS
        ):  # quarterly dividends, ex-date ~5th of Jan/Apr/Jul/Oct, announced 3 weeks before
            for y in (2022, 2023, 2024):
                for m in (1, 4, 7, 10):
                    ex = _nearest_bday(date(y, m, 5), days)
                    i = days.index(ex)
                    actions.append(
                        CorporateAction(
                            source_id=SRC,
                            origin=SYN,
                            available_at=end_of_day_utc(ex - timedelta(days=21)),
                            security_id=t,
                            ex_date=ex,
                            kind=CorporateActionKind.DIVIDEND,
                            value=round(float(price[max(i - 1, 0)]) * 0.007, 4),
                        )
                    )

    # Macro: DFF follows the synthetic FOMC path; DGS2/DGS10 random walks. Next-day availability.
    observations: list[Observation] = []
    rate = 0.08
    moves = {d: bps for d, bps in FOMC}
    dgs2, dgs10 = 0.75, 1.65
    for d in days:
        if d in moves:
            rate = round(rate + moves[d] / 100, 2)
        dgs2 = max(0.1, dgs2 + rng.normal(0.004, 0.05))
        dgs10 = max(0.5, dgs10 + rng.normal(0.002, 0.04))
        avail = et(d + timedelta(days=1), 16, 0)
        for mid, val in (("DFF", rate), ("DGS2", dgs2), ("DGS10", dgs10)):
            observations.append(
                Observation(
                    source_id=SRC,
                    origin=SYN,
                    available_at=avail,
                    availability_inferred=True,
                    metric_id=mid,
                    economy="US",
                    period_end=d,
                    value=round(float(val), 3),
                    unit="percent",
                )
            )

    events: list[Event] = []
    for d, bps in FOMC:
        eid = f"fomc-{d.isoformat()}"
        base = {
            "event_id": eid,
            "event_class": EventClass.SCHEDULED,
            "subtype": "fomc_meeting",
            "title": f"FOMC decision {d.isoformat()}",
            "scope": EventScope.MARKET,
            "scheduled_at": et(d, 14, 0),
            "affected_security_ids": list(BANKS),
            "source_ids": ["synthetic:fomc-calendar"],
            "source_id": SRC,
            "origin": SYN,
        }
        events.append(
            Event(
                **base,
                status=EventStatus.UPCOMING,
                revision=0,
                available_at=end_of_day_utc(date(d.year, 1, 2) - timedelta(days=60)),
            )
        )
        outcome = "hold" if bps == 0 else f"{'+' if bps > 0 else ''}{bps} bps"
        events.append(
            Event(
                **base,
                status=EventStatus.OCCURRED,
                revision=1,
                occurred_at=et(d, 14, 0),
                published_at=et(d, 14, 0),
                actual_outcome=outcome,
                surprise=0.0,
                available_at=et(d, 14, 0),
            )
        )

    for t in BANKS:  # quarterly results ~14th of Jan/Apr/Jul/Oct, pre-market
        for y in (2022, 2023, 2024):
            for m in (1, 4, 7, 10):
                d = _nearest_bday(date(y, m, 14), days)
                eid = f"earnings-{t}-{d.isoformat()}"
                surprise = round(float(rng.normal(0.03, 0.06)), 3)
                base = {
                    "event_id": eid,
                    "event_class": EventClass.SCHEDULED,
                    "subtype": "quarterly_results",
                    "title": f"{t} quarterly results",
                    "scope": EventScope.FIRM,
                    "scheduled_at": et(d, 7, 0),
                    "affected_security_ids": [t],
                    "source_ids": [f"synthetic:earnings:{t}"],
                    "source_id": SRC,
                    "origin": SYN,
                }
                events.append(
                    Event(
                        **base,
                        status=EventStatus.UPCOMING,
                        revision=0,
                        expected_outcome="EPS in line with consensus",
                        available_at=end_of_day_utc(d - timedelta(days=30)),
                    )
                )
                events.append(
                    Event(
                        **base,
                        status=EventStatus.OCCURRED,
                        revision=1,
                        occurred_at=et(d, 7, 0),
                        published_at=et(d, 7, 0),
                        actual_outcome=f"EPS surprise {surprise:+.1%}",
                        surprise=surprise,
                        available_at=et(d, 7, 0),
                    )
                )
                observations.append(
                    Observation(
                        source_id=SRC,
                        origin=SYN,
                        available_at=et(d, 7, 0),
                        metric_id="eps_surprise_pct",
                        security_id=t,
                        period_end=d - timedelta(days=14),
                        value=surprise * 100,
                        unit="percent",
                    )
                )

    events.append(
        Event(
            source_id=SRC,
            origin=SYN,
            event_id="stress-2023-03-13",
            event_class=EventClass.UNEXPECTED,
            subtype="sector_stress",
            title="Synthetic sector stress (deposit-flight scenario)",
            status=EventStatus.OCCURRED,
            scope=EventScope.SECTOR,
            occurred_at=et(SHOCK_DATE, 9, 30),
            published_at=et(SHOCK_DATE, 9, 30),
            affected_security_ids=list(BANKS),
            source_ids=["synthetic:news"],
            available_at=et(SHOCK_DATE, 9, 30),
        )
    )
    capital = {
        "source_id": SRC,
        "origin": SYN,
        "event_id": "reg-capital-rule",
        "event_class": EventClass.ANTICIPATED,
        "subtype": "regulatory_development",
        "title": "Proposed higher bank capital requirements",
        "scope": EventScope.SECTOR,
        "affected_security_ids": list(BANKS),
        "source_ids": ["synthetic:regulator"],
    }
    events.append(
        Event(
            **capital,
            status=EventStatus.UPCOMING,
            revision=0,
            expected_outcome="Proposal may raise capital requirements",
            available_at=end_of_day_utc(date(2023, 5, 1)),
        )
    )
    events.append(
        Event(
            **capital,
            status=EventStatus.OCCURRED,
            revision=1,
            occurred_at=et(date(2023, 7, 27), 10, 0),
            published_at=et(date(2023, 7, 27), 10, 0),
            actual_outcome="Proposal published",
            available_at=et(date(2023, 7, 27), 10, 0),
        )
    )

    analyst: list[AnalystObservation] = []
    firms = ["Synthetic Research A", "Synthetic Research B"]
    for t in BANKS:
        for k, d in enumerate(
            [date(2022, 6, 1), date(2023, 2, 1), date(2023, 4, 3), date(2024, 5, 1)]
        ):
            d = _nearest_bday(d, days)
            px = next(b.raw_close for b in bars if b.security_id == t and b.trading_date == d)
            up = (k + len(t)) % 3 != 0
            analyst.append(
                AnalystObservation(
                    source_id=SRC,
                    origin=SYN,
                    available_at=end_of_day_utc(d),
                    availability_inferred=True,
                    observation_id=f"an-{t}-{d.isoformat()}",
                    analyst_source=firms[k % 2],
                    security_id=t,
                    action=AnalystAction.UPGRADE if up else AnalystAction.DOWNGRADE,
                    from_rating="Neutral" if up else "Buy",
                    to_rating="Buy" if up else "Neutral",
                    target_price=round(px * (1.15 if up else 0.97), 2),
                    horizon_months=12,
                    assumptions="Net interest income " + ("expands" if up else "compresses"),
                    issued_at=end_of_day_utc(d),
                )
            )

    return SyntheticDataset(_securities(), bars, actions, observations, events, analyst, days)


def synthetic_as_of(d: date | None = None) -> datetime:
    """Default as-of for synthetic runs: after the close on ``d`` (default: last fixture day)."""
    return end_of_day_utc(d or END)
