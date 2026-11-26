"""Parsing of ``as_of`` (docs/api.md): a date means 23:59 New York that day; a datetime must be
timezone-aware. Applies to query strings and to the top-level ``as_of`` of JSON bodies."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Coroutine
from datetime import date, datetime
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute

from forwardstate.pit import as_of_for_date, ensure_utc

from .errors import invalid

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_as_of(value: str | None, field: str = "as_of") -> datetime | None:
    """Parse a user-supplied as_of. ``None``/empty means 'use the default'."""
    if value is None or value == "":
        return None
    text = value.strip()
    if _DATE_RE.match(text):
        try:
            return as_of_for_date(date.fromisoformat(text))
        except ValueError as e:
            raise invalid(f"Invalid date '{value}': {e}", field, "invalid_as_of") from e
    text = text.replace("Z", "+00:00")
    if "T" in text and text.count(" ") == 1:
        # An unencoded '+' in a query string arrives as a space: '...T10:00:00 00:00'.
        text = text.replace(" ", "+")
    try:
        ts = datetime.fromisoformat(text)
    except ValueError as e:
        raise invalid(
            f"Invalid as_of '{value}'. Use YYYY-MM-DD or an ISO datetime with a timezone.",
            field, "invalid_as_of",
        ) from e
    if ts.tzinfo is None:
        raise invalid(
            f"as_of '{value}' has no timezone. Add 'Z' or an offset such as '+00:00'.",
            field, "invalid_as_of",
        )
    return ensure_utc(ts)


def _rewrite_body(raw: bytes) -> bytes:
    """Turn a top-level ``"as_of": "YYYY-MM-DD"`` into the D007 as-of instant (23:59 New York)."""
    if not raw:
        return raw
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return raw  # let FastAPI report the JSON error
    if isinstance(data, dict) and isinstance(data.get("as_of"), str) and _DATE_RE.match(
        data["as_of"].strip()
    ):
        try:
            d = date.fromisoformat(data["as_of"].strip())
        except ValueError:
            return raw  # pydantic will report it
        data["as_of"] = as_of_for_date(d).isoformat()
        return json.dumps(data).encode()
    return raw


class _AsOfRequest(Request):
    async def body(self) -> bytes:
        if not getattr(self, "_fs_rewritten", False):
            raw = await super().body()
            self._body = _rewrite_body(raw)
            self._fs_rewritten = True
        return self._body


class AsOfRoute(APIRoute):
    """Route class that accepts a plain date for the body ``as_of`` field."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            return await original(_AsOfRequest(request.scope, request.receive))

        return handler
