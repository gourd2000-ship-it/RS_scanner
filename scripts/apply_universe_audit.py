"""승인된 universe audit decision만 안전하게 반영한다.

승인과 적용은 의도적으로 별도 명령이다.

예시:
    .venv/bin/python scripts/apply_universe_audit.py approve 12 --approved-by operator
    .venv/bin/python scripts/apply_universe_audit.py apply 3 --applied-by operator
"""

from __future__ import annotations

import argparse

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.repositories.universe_audit_repository import (
    UniverseAuditApplyResult,
    UniverseAuditRepository,
)


def approve_decision(
    session: Session,
    *,
    decision_id: int,
    approved_by: str,
):
    """pending legacy deactivation decision을 승인만 한다."""
    return UniverseAuditRepository(session).approve_deactivation(
        decision_id=decision_id,
        approved_by=approved_by,
    )


def apply_run(
    session: Session,
    *,
    run_id: int,
    applied_by: str,
) -> UniverseAuditApplyResult:
    """해당 run에서 이미 승인된 deactivate decision만 반영한다."""
    return UniverseAuditRepository(session).apply_approved_deactivations(
        run_id=run_id,
        applied_by=applied_by,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="승인 기반 universe audit 반영")
    subparsers = parser.add_subparsers(dest="command", required=True)

    approve_parser = subparsers.add_parser("approve", help="deactivate decision 승인")
    approve_parser.add_argument("decision_id", type=int)
    approve_parser.add_argument("--approved-by", required=True)

    apply_parser = subparsers.add_parser("apply", help="승인된 decision 반영")
    apply_parser.add_argument("run_id", type=int)
    apply_parser.add_argument("--applied-by", required=True)

    args = parser.parse_args()
    with SessionLocal() as session:
        try:
            if args.command == "approve":
                decision = approve_decision(
                    session,
                    decision_id=args.decision_id,
                    approved_by=args.approved_by,
                )
                session.commit()
                print(
                    "universe audit decision approved: "
                    f"decision_id={decision.id} run_id={decision.run_id}"
                )
                return 0

            outcome = apply_run(
                session,
                run_id=args.run_id,
                applied_by=args.applied_by,
            )
            session.commit()
            print(
                "universe audit apply completed: "
                f"run_id={outcome.run_id} applied_count={outcome.applied_count}"
            )
            return 0
        except ValueError as exc:
            session.rollback()
            parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
