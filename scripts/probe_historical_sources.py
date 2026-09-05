#!/usr/bin/env python3
"""Run bounded, read-only Kiwoom probes for the BT01 source contract."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, ".")

from app.core.config import get_settings
from app.crawler.kiwoom_client import KiwoomRestClient
from app.crawler.parsers.kiwoom import parse_kiwoom_daily_prices
from app.services.historical_source_contract import (
    HistoricalProbeRequest,
    default_probe_requests,
    probe_kiwoom_daily_history,
)


def _date_argument(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("dates must use YYYYMMDD") from exc


def _sample_argument(value: str) -> tuple[str, str]:
    code, separator, label = value.partition(":")
    if not separator or not code or not label:
        raise argparse.ArgumentTypeError("--sample must use CODE:LABEL")
    return code, label


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-date",
        required=True,
        help="fixed Kiwoom base date (YYYYMMDD); 00000000 is not accepted",
    )
    parser.add_argument(
        "--target-date",
        type=_date_argument,
        default=date(2013, 1, 1),
        help="earliest date whose reachability is measured (YYYYMMDD)",
    )
    parser.add_argument("--max-pages", type=int, default=8)
    parser.add_argument(
        "--sample",
        action="append",
        type=_sample_argument,
        metavar="CODE:LABEL",
        help="override the six documented samples; repeat for each sample",
    )
    parser.add_argument("--output", type=Path, help="optional JSON result path")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.sample:
        requests = tuple(
            HistoricalProbeRequest(
                code=code,
                label=label,
                base_date=args.base_date,
                target_date=args.target_date,
                max_pages=args.max_pages,
            )
            for code, label in args.sample
        )
    else:
        requests = default_probe_requests(
            base_date=args.base_date,
            target_date=args.target_date,
            max_pages=args.max_pages,
        )

    settings = get_settings()
    client = KiwoomRestClient(settings=settings)
    results = [
        probe_kiwoom_daily_history(
            request,
            fetch_page=client.fetch_daily_chart_page,
            parse_page=parse_kiwoom_daily_prices,
        )
        for request in requests
    ]
    target_reached_count = sum(result.target_reached for result in results)
    fully_traversed_count = sum(
        result.terminal_reason == "completed" for result in results
    )
    document = {
        "contract_version": "bt01-kiwoom-probe-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "kiwoom_rest",
        "tr": "ka10081",
        "base_date": args.base_date,
        "target_date": args.target_date.isoformat(),
        "max_pages": args.max_pages,
        "adjusted_price_type": settings.kiwoom_adjusted_price_type,
        "sample_count": len(results),
        "target_reached_count": target_reached_count,
        "fully_traversed_count": fully_traversed_count,
        "status": "complete" if target_reached_count == len(results) else "partial",
        "samples": [result.as_dict() for result in results],
    }
    rendered = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
