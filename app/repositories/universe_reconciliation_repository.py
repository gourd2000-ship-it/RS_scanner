"""Persistence for idempotent KRX/Naver reconciliation runs."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.universe_reconciliation import UniverseReconciliationRun


class UniverseReconciliationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create_run(
        self,
        *,
        krx_snapshot_id: int,
        naver_snapshot_id: int,
        report: dict,
    ) -> UniverseReconciliationRun:
        existing = self.session.scalar(
            select(UniverseReconciliationRun).where(
                UniverseReconciliationRun.krx_snapshot_id == krx_snapshot_id,
                UniverseReconciliationRun.naver_snapshot_id == naver_snapshot_id,
            )
        )
        if existing is not None:
            return existing
        run = UniverseReconciliationRun(
            krx_snapshot_id=krx_snapshot_id,
            naver_snapshot_id=naver_snapshot_id,
            report=report,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def approve_run(
        self,
        run_id: int,
        *,
        approved_by: str,
    ) -> UniverseReconciliationRun:
        """Record an explicit operator approval without changing report evidence."""
        reviewer = approved_by.strip()
        if not reviewer:
            raise ValueError("approved_by는 비어 있을 수 없습니다")
        run = self.session.get(UniverseReconciliationRun, run_id)
        if run is None:
            raise ValueError(f"reconciliation run을 찾을 수 없습니다: {run_id}")
        if run.status != "pending_review":
            raise ValueError(f"pending_review 상태가 아닌 run은 승인할 수 없습니다: {run_id}")
        run.status = "approved"
        run.decision = "approved"
        run.approved_by = reviewer
        run.decided_at = datetime.utcnow()
        self.session.flush()
        return run
