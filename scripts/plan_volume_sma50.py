"""Create a read-only JSON report for volume 50-day moving averages."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.market_calendar import krx_market_day_status
from app.models.instrument import ProviderSymbol
from app.services.indicators.contracts import EmaSourcePolicy, canonical_json
from app.services.indicators.volume_service import VolumeSmaService


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("YYYY-MM-DD 형식이어야 합니다") from exc


def _utc_datetime(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("UTC RFC 3339 시각이어야 합니다") from exc
    if result.tzinfo is None:
        raise argparse.ArgumentTypeError("UTC offset 또는 Z가 필요합니다")
    return result.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, type=_date)
    parser.add_argument("--end", required=True, type=_date)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--adjustment-type", required=True)
    parser.add_argument("--parser-version", action="append", required=True)
    parser.add_argument("--observation-cutoff", required=True, type=_utc_datetime)
    parser.add_argument("--instrument-id", type=int, action="append", default=[])
    parser.add_argument("--output", type=Path)
    return parser


def execute(args: argparse.Namespace) -> dict[str, Any]:
    if args.end < args.start:
        raise ValueError("end는 start보다 빠를 수 없습니다")
    policy = EmaSourcePolicy(
        provider=args.provider,
        adjustment_type=args.adjustment_type,
        allowed_parser_versions=tuple(sorted(set(args.parser_version))),
        observation_cutoff=args.observation_cutoff,
    )
    dates = tuple(_trading_dates(args.start, args.end))
    if not dates:
        raise ValueError("범위에 KRX 거래일이 없습니다")
    with SessionLocal() as session:
        ids = tuple(sorted(set(args.instrument_id))) or tuple(session.scalars(
            select(ProviderSymbol.instrument_id).where(
                ProviderSymbol.provider == policy.provider,
                ProviderSymbol.mapping_status == "matched",
            ).distinct().order_by(ProviderSymbol.instrument_id)
        ))
        service = VolumeSmaService(session)
        targets: list[dict[str, Any]] = []
        totals = Counter()
        for instrument_id in ids:
            result = service.calculate(instrument_id=instrument_id, trade_dates=dates, policy=policy)
            counts = Counter(value.status.value for value in result.values)
            first_available = next((value.trade_date.isoformat() for value in result.values if value.status.value == "available"), None)
            targets.append({
                "instrument_id": instrument_id,
                "first_available": first_available,
                "warming_up_rows": counts["warming_up"],
                "data_unavailable_rows": counts["data_unavailable"],
                "available_rows": counts["available"],
                "result_hash": result.result_hash,
            })
            totals.update(counts)
    report_without_hash = {
        "schema_version": 1,
        "mode": "read_only_plan",
        "indicator": "volume_sma_50",
        "request": {
            "start": args.start,
            "end": args.end,
            "policy": policy.fingerprint_material(),
            "instrument_ids": ids,
        },
        "counts": {"targets": len(targets), **{status: totals[status] for status in ("warming_up", "data_unavailable", "available")}},
        "targets": targets,
    }
    from hashlib import sha256
    return {**json.loads(canonical_json(report_without_hash)), "report_hash": sha256(canonical_json(report_without_hash).encode("utf-8")).hexdigest()}


def _trading_dates(start: date, end: date):
    current = start
    while current <= end:
        if krx_market_day_status(current).is_open:
            yield current
        current += timedelta(days=1)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = execute(args)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
