"""Record an operator's approval for one KRX/Naver reconciliation run."""

from __future__ import annotations

import argparse
import json

from app.core.database import session_scope
from app.repositories.universe_reconciliation_repository import UniverseReconciliationRepository


def main() -> int:
    parser = argparse.ArgumentParser(description="KRX/Naver reconciliation 운영 승인 기록")
    parser.add_argument("--run-id", type=int, required=True, help="승인할 reconciliation run ID")
    parser.add_argument(
        "--approved-by",
        required=True,
        help="리포트를 검토한 운영자 식별자",
    )
    args = parser.parse_args()
    try:
        with session_scope() as session:
            run = UniverseReconciliationRepository(session).approve_run(
                args.run_id,
                approved_by=args.approved_by,
            )
            payload = {
                "id": run.id,
                "status": run.status,
                "decision": run.decision,
                "approved_by": run.approved_by,
                "decided_at": run.decided_at.isoformat() if run.decided_at else None,
            }
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
