"""Record one operator KRX canary decision from batch evidence."""

from __future__ import annotations

import argparse
import json

from app.core.database import session_scope
from app.services.universe_canary_decision import record_canary_decision


def main() -> int:
    parser = argparse.ArgumentParser(description="KRX canary 일별 운영 결정 기록")
    parser.add_argument("--job-id", type=int, required=True)
    parser.add_argument("--market", required=True, help="예: KOSPI")
    parser.add_argument(
        "--decision",
        required=True,
        choices=("continue", "expand", "rollback"),
    )
    parser.add_argument("--approved-by", required=True, help="리포트를 검토한 운영자 식별자")
    parser.add_argument("--notes", default=None)
    args = parser.parse_args()
    try:
        with session_scope() as session:
            decision = record_canary_decision(
                session,
                crawl_job_id=args.job_id,
                market=args.market,
                operator_decision=args.decision,
                approved_by=args.approved_by,
                notes=args.notes,
            )
            payload = {
                "id": decision.id,
                "crawl_job_id": decision.crawl_job_id,
                "trade_date": decision.trade_date.isoformat(),
                "market": decision.market,
                "authority": decision.authority,
                "fallback_reason": decision.fallback_reason,
                "mapping_rate": decision.mapping_rate,
                "target_count": decision.target_count,
                "operator_decision": decision.operator_decision,
                "approved_by": decision.approved_by,
                "decided_at": decision.decided_at.isoformat(),
            }
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
