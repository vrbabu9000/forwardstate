"""as_of parsing: a date means 23:59 New York; a datetime must be timezone-aware."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from forwardstate.api.asof import _rewrite_body, parse_as_of
from forwardstate.api.errors import ApiError
from forwardstate.pit import as_of_for_date


def test_empty_means_default():
    assert parse_as_of(None) is None
    assert parse_as_of("") is None


def test_date_is_end_of_day_new_york():
    got = parse_as_of("2024-01-02")
    assert got == as_of_for_date(date(2024, 1, 2))
    assert got == datetime(2024, 1, 3, 4, 59, tzinfo=timezone.utc)  # EST = UTC-5


def test_date_in_summer_uses_edt():
    assert parse_as_of("2024-07-01") == datetime(2024, 7, 2, 3, 59, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "text",
    ["2024-01-02T15:00:00Z", "2024-01-02T15:00:00+00:00", "2024-01-02T10:00:00-05:00",
     "2024-01-02T15:00:00 00:00"],  # '+' decoded as a space in a query string
)
def test_aware_datetimes_become_utc(text):
    got = parse_as_of(text)
    assert got == datetime(2024, 1, 2, 15, 0, tzinfo=timezone.utc)
    assert got.tzinfo == timezone.utc


@pytest.mark.parametrize("text", ["2024-01-02T15:00:00", "2024-13-01", "soon", "2024-02-30"])
def test_rejected(text):
    with pytest.raises(ApiError) as e:
        parse_as_of(text)
    assert e.value.status == 422 and e.value.field == "as_of"


def test_body_date_is_rewritten_only_at_top_level():
    out = json.loads(_rewrite_body(b'{"as_of": "2024-01-02", "x": {"as_of": "2024-01-02"}}'))
    assert out["as_of"] == as_of_for_date(date(2024, 1, 2)).isoformat()
    assert out["x"]["as_of"] == "2024-01-02"
    same = b'{"as_of": "2024-01-02T15:00:00Z"}'
    assert _rewrite_body(same) == same
    assert _rewrite_body(b"not json") == b"not json"
