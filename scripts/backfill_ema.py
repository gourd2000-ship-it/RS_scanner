"""Plan or explicitly apply bounded, historical EMA 5/20/50/200 calculations.

The default is a strict database read-only dry-run.  ``--apply`` is required
to create immutable EMA series, generations, calculation runs, snapshots, and
values.  Repeating the same applied command, including with ``--resume``,
reuses completed runs; it never updates completed EMA evidence.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.core.database import SessionLocal
from app.services.indicators.backfill import EmaHistoricalBackfillRequest, EmaHistoricalBackfillService
from app.services.indicators.contracts import EmaSourcePolicy


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("YYYY-MM-DD 형식이어야 합니다") from exc


def _parse_utc_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("UTC RFC 3339 시각이어야 합니다 (예: 2026-10-02T08:40:00Z)") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("observation cutoff에는 UTC offset 또는 Z가 필요합니다")
    return parsed.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, type=_parse_date, help="포함할 시작 거래일 범위")
    parser.add_argument("--end", required=True, type=_parse_date, help="포함할 종료 거래일 범위")
    parser.add_argument("--provider", required=True, help="고정할 EMA 입력 공급자")
    parser.add_argument("--adjustment-type", required=True, help="고정할 공급자 조정 기준")
    parser.add_argument(
        "--parser-version",
        action="append",
        required=True,
        help="허용할 parser version (여러 개는 옵션을 반복)",
    )
    parser.add_argument(
        "--observation-cutoff",
        required=True,
        type=_parse_utc_datetime,
        help="입력 선택에 고정할 UTC cutoff (예: 2026-10-02T08:40:00Z)",
    )
    parser.add_argument(
        "--instrument-id",
        type=int,
        action="append",
        default=[],
        help="대상 historical instrument ID (반복 가능, 생략 시 정책 일치 immutable identity 대상 전체)",
    )
    parser.add_argument("--chunk-size", type=int, default=50, help="커밋 경계당 최대 종목 수 (1~500)")
    parser.add_argument("--apply", action="store_true", help="검토된 계획을 실제 DB에 적용")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="같은 범위·정책 실행을 재개; 완료된 동일 input hash run은 재사용",
    )
    parser.add_argument("--output", type=Path, help="JSON report 저장 경로 (기본은 stdout)")
    return parser


def request_from_args(args: argparse.Namespace) -> EmaHistoricalBackfillRequest:
    policy = EmaSourcePolicy(
        provider=args.provider,
        adjustment_type=args.adjustment_type,
        allowed_parser_versions=tuple(sorted(set(args.parser_version))),
        observation_cutoff=args.observation_cutoff,
    )
    return EmaHistoricalBackfillRequest(
        start=args.start,
        end=args.end,
        policy=policy,
        instrument_ids=tuple(args.instrument_id),
        chunk_size=args.chunk_size,
    )


def execute(args: argparse.Namespace) -> dict[str, Any]:
    if args.resume and not args.apply:
        raise ValueError("--resume은 --apply와 함께 사용해야 합니다")
    request = request_from_args(args)
    with SessionLocal() as session:
        service = EmaHistoricalBackfillService(session)
        # The market-wide historical range is too large for the bounded in
        # memory plan object.  The streaming report retains only compact
        # instrument summaries and has the same deterministic report contract.
        plan_report = service.streaming_plan_report(request)
        if not args.apply:
            # Session.close() rolls back the read transaction.  No write-capable
            # calculation service method is reached on the dry-run path.
            return plan_report
        application = service.apply_request(
            request,
            plan_report_hash=plan_report["report_hash"],
            resume=args.resume,
        )
        return {"plan": plan_report, "application": application.report()}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = execute(args)
    except ValueError as exc:
        parser.error(str(exc))
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"EMA {'apply' if args.apply else 'dry-run'} report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
