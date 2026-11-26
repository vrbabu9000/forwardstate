"""Command line: ``forwardstate fetch`` (ingest real data) and ``forwardstate serve`` (API)."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="forwardstate", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="Fetch real open data into the local point-in-time store.")
    f.add_argument("--start", default="2015-01-01", help="First date to fetch (YYYY-MM-DD).")
    f.add_argument("--sources", default="all", help="Comma list: yahoo,fred,edgar,fomc or 'all'.")
    f.add_argument("--tickers", default=None, help="Override tickers (default: sector universe + benchmarks).")

    s = sub.add_parser("serve", help="Run the API server.")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--reload", action="store_true")

    args = parser.parse_args(argv)
    if args.cmd == "fetch":
        from forwardstate.ingest.fetch import run_fetch  # implemented by the data layer

        return run_fetch(start=args.start, sources=args.sources, tickers=args.tickers)
    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("forwardstate.api.app:app", host=args.host, port=args.port, reload=args.reload)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
