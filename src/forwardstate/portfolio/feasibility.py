"""Feasibility checks for a portfolio and its constraints (BRD p.7, AC-04).

Every problem becomes a ``FeasibilityIssue`` with a code and a plain-English message. All
problems are reported, not just the first. Constraints are never changed here.
"""

from __future__ import annotations

from collections import Counter

from forwardstate.contracts import CASH_ID, FeasibilityIssue, Portfolio, Security

TOL = 1e-6

# Issues that make the current portfolio impossible to compute.
BLOCKING_CODES = {"unknown_security", "not_investable", "duplicate_security"}


def investable_universe(securities: list[Security]) -> list[str]:
    """Investable security ids (benchmarks excluded), store order, CASH last."""
    ids = [s.security_id for s in securities if s.investable and s.security_id != CASH_ID]
    return [*ids, CASH_ID]


def check_feasibility(portfolio: Portfolio, securities: list[Security]) -> list[FeasibilityIssue]:
    c = portfolio.constraints
    known = {s.security_id: s for s in securities}
    issues: list[FeasibilityIssue] = []

    total = sum(h.weight for h in portfolio.holdings)
    if abs(total - 1.0) > TOL:
        issues.append(FeasibilityIssue(
            code="weights_sum",
            message=f"Weights add up to {total:.2%}. They must add up to 100%.",
            field="holdings",
        ))

    for sid, n in sorted(Counter(h.security_id for h in portfolio.holdings).items()):
        if n > 1:
            issues.append(FeasibilityIssue(
                code="duplicate_security",
                message=f"{sid} is listed {n} times. List each holding once.",
                field="holdings",
            ))

    for i, h in enumerate(portfolio.holdings):
        sid = h.security_id
        if sid == CASH_ID:
            continue
        sec = known.get(sid)
        if sec is None:
            issues.append(FeasibilityIssue(
                code="unknown_security",
                message=f"{sid} is not in the supported universe.",
                field=f"holdings[{i}].security_id",
            ))
        elif not sec.investable:
            issues.append(FeasibilityIssue(
                code="not_investable",
                message=f"{sid} is a benchmark used for comparison only. It cannot be held.",
                field=f"holdings[{i}].security_id",
            ))
        if h.weight > c.max_position_weight + TOL:
            issues.append(FeasibilityIssue(
                code="max_position",
                message=f"{sid} is {h.weight:.1%} of the portfolio, above your maximum position "
                f"of {c.max_position_weight:.1%}.",
                field=f"holdings[{i}].weight",
            ))

    if c.min_cash_weight > c.max_cash_weight + TOL:
        issues.append(FeasibilityIssue(
            code="cash_bounds",
            message=f"Minimum cash ({c.min_cash_weight:.1%}) is above maximum cash "
            f"({c.max_cash_weight:.1%}).",
            field="constraints.min_cash_weight",
        ))
    cash = sum(h.weight for h in portfolio.holdings if h.security_id == CASH_ID)
    if cash < c.min_cash_weight - TOL:
        issues.append(FeasibilityIssue(
            code="cash_bounds",
            message=f"Cash is {cash:.1%}, below your minimum cash of {c.min_cash_weight:.1%}.",
            field="constraints.min_cash_weight",
        ))
    if cash > c.max_cash_weight + TOL:
        issues.append(FeasibilityIssue(
            code="cash_bounds",
            message=f"Cash is {cash:.1%}, above your maximum cash of {c.max_cash_weight:.1%}.",
            field="constraints.max_cash_weight",
        ))

    n_risky = len(investable_universe(securities)) - 1
    reach = n_risky * c.max_position_weight + c.max_cash_weight
    if reach < 1.0 - TOL:
        issues.append(FeasibilityIssue(
            code="bounds_infeasible",
            message=f"No portfolio can meet these limits: {n_risky} securities at most "
            f"{c.max_position_weight:.1%} each plus at most {c.max_cash_weight:.1%} cash reach "
            f"only {reach:.1%}, not 100%.",
            field="constraints",
        ))
    return issues
