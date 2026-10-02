#!/usr/bin/env python3
"""Run or resume an explicit Kiwoom historical-price backfill manifest."""

import argparse
from datetime import date
import json
from uuid import uuid4

from app.core.database import session_scope
from app.crawler.sources.kiwoom_history import KiwoomHistoryRequest, iter_kiwoom_history
from app.repositories.historical_backfill_repository import HistoricalBackfillRepository
from app.repositories.price_repository import PriceRepository
from app.services.historical_backfill import HistoricalBackfillService, plan_from_manifest, plan_from_serialized
from app.services.historical_universe import HistoricalUniverseRequest, build_historical_universe


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, type=_parse_date)
    parser.add_argument("--end", required=True, type=_parse_date)
    parser.add_argument("--base-date", required=True, help="fixed Kiwoom YYYYMMDD base date")
    parser.add_argument("--provider", default="kiwoom")
    parser.add_argument("--adjustment-type", default="1")
    parser.add_argument("--request-budget", type=int, default=500)
    parser.add_argument("--additional-request-budget", type=int, default=0, help="--resume run에 추가할 승인 요청 한도")
    parser.add_argument("--only-pending", action="store_true", help="재개 시 partial/running target은 보존하고 pending만 처리")
    parser.add_argument("--market", action="append", dest="markets", choices=("KOSPI", "KOSDAQ"))
    parser.add_argument("--symbol", action="append", dest="symbols", help="provider code filter")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--resume", action="store_true", help="require an existing --run-id")
    parser.add_argument(
        "--finalize-confirmed-start", action="store_true",
        help="legacy running targets that already observed their first expected date만 완료 처리",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.resume and not args.run_id:
        parser.error("--resume requires --run-id")
    if args.additional_request_budget and not args.resume:
        parser.error("--additional-request-budget requires --resume")
    if args.finalize_confirmed_start and not args.resume:
        parser.error("--finalize-confirmed-start requires --resume")
    if args.resume and args.symbols:
        parser.error("--resume cannot change the frozen target set with --symbol")
    run_id = args.run_id or f"historical-{uuid4()}"
    with session_scope() as session:
        if args.resume:
            existing = HistoricalBackfillRepository(session).get_run(run_id)
            if existing is None:
                raise ValueError(f"resume할 backfill run을 찾을 수 없습니다: {run_id}")
            plan = plan_from_serialized(existing.manifest)
            _validate_resume_args(args, plan)
        else:
            manifest = build_historical_universe(
                session, HistoricalUniverseRequest(args.start, args.end, markets=tuple(args.markets or ("KOSPI", "KOSDAQ")))
            )
            plan = plan_from_manifest(
                session, manifest, provider=args.provider, adjustment_type=args.adjustment_type,
                base_date=args.base_date, request_budget=args.request_budget, dry_run=args.dry_run,
            )
        if args.symbols:
            wanted = set(args.symbols)
            plan = plan.__class__(
                start=plan.start, end=plan.end, provider=plan.provider, adjustment_type=plan.adjustment_type,
                base_date=plan.base_date, request_budget=plan.request_budget, dry_run=plan.dry_run,
                targets=tuple(target for target in plan.targets if target.provider_code in wanted),
            )
        service = HistoricalBackfillService(session, HistoricalBackfillRepository(session), PriceRepository(session))
        if args.finalize_confirmed_start:
            reconciled = service.reconcile_targets_with_confirmed_start(run_id)
            run = HistoricalBackfillRepository(session).get_run(run_id)
            print(json.dumps({
                "run_id": run_id,
                "reconciled_targets": reconciled,
                "status": run.status,
                "manifest_hash": run.manifest_hash,
            }, ensure_ascii=False, sort_keys=True))
            return 0
        report = service.execute(
            run_id, plan,
            lambda target, remaining_requests: iter_kiwoom_history(KiwoomHistoryRequest(
                code=target.provider_code, start=args.start, end=args.end, base_date=args.base_date,
                market=target.market, adjustment_type=args.adjustment_type, request_budget=remaining_requests,
            )),
            additional_request_budget=args.additional_request_budget,
            process_statuses=("pending",) if args.only_pending else ("pending", "running"),
        )
    print(json.dumps(report.__dict__, ensure_ascii=False, sort_keys=True))
    return 0


def _validate_resume_args(args, plan) -> None:
    """재개 명령이 frozen lifecycle/price 정책을 바꾸지 못하게 한다."""
    supplied = (args.start, args.end, args.provider, args.adjustment_type, args.base_date, args.dry_run)
    frozen = (plan.start, plan.end, plan.provider, plan.adjustment_type, plan.base_date, plan.dry_run)
    if supplied != frozen:
        raise ValueError("resume settings differ from the frozen manifest")


if __name__ == "__main__":
    raise SystemExit(main())
