"""Synthetic price-stage benchmark for the CRAWL-10 tuning loop.

This is a local harness, not a substitute for staging.  It exercises the same
chunking, bounded fetch concurrency, status accounting and request budget used
by the batch service, and writes a JSON artifact that can be compared with a
staging run.
"""

from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
from time import perf_counter

from app.core.metrics import metrics
from app.schemas.market_data import DailyPricePayload, SymbolPayload
from app.services.batch.context import build_memory_batch_context
from app.services.batch.sync_prices import sync_prices


class SyntheticPriceSource:
    max_concurrency = 4

    def __init__(self, symbols: list[SymbolPayload]) -> None:
        self.symbols = symbols

    def fetch_daily_prices(self, code: str, since_date=None):
        value = Decimal("100")
        return [
            DailyPricePayload(
                trade_date=date.today(),
                open=value,
                high=value,
                low=value,
                close=value,
                volume=1,
                change_rate=Decimal("0"),
            )
        ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", type=int, default=2400)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    if args.symbols < 1 or args.workers < 1:
        parser.error("--symbols and --workers must be positive")

    symbols = [
        SymbolPayload(
            code=f"{index:06d}",
            name=f"Synthetic {index}",
            market="KOSPI" if index % 2 else "KOSDAQ",
        )
        for index in range(args.symbols)
    ]
    source = SyntheticPriceSource(symbols)
    source.max_concurrency = args.workers
    context = build_memory_batch_context()
    context.symbol_repository.upsert_many(symbols)
    metrics.reset()
    started = perf_counter()
    result = sync_prices(context, source, max_requests=args.symbols)
    elapsed = perf_counter() - started
    payload = {
        "target_count": result.target_count,
        "fetched": result.fetched_count,
        "no_new_data": result.no_new_data_count,
        "partial": result.partial_count,
        "failed": result.failed_count,
        "skipped": result.skipped_count,
        "coverage_rate": (
            (result.fetched_count + result.no_new_data_count + result.skipped_count)
            / result.target_count
            if result.target_count
            else 0.0
        ),
        "duration_seconds": elapsed,
        "workers": args.workers,
        "metrics": metrics.snapshot(),
    }
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
