"""승인된 universe legacy 정리를 감사 가능하게 반영한다."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.symbol import Symbol
from app.models.universe_audit import UniverseAuditDecision, UniverseAuditRun
from app.services.universe_audit import UniverseAuditReport


@dataclass(frozen=True)
class UniverseAuditApplyResult:
    run_id: int
    applied_count: int


class UniverseAuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_run(
        self,
        *,
        snapshot_id: int | None,
        report: UniverseAuditReport,
        requested_by: str,
    ) -> UniverseAuditRun:
        run = UniverseAuditRun(
            snapshot_id=snapshot_id,
            requested_by=requested_by,
            report=report.to_dict(),
        )
        self.session.add(run)
        self.session.flush()

        symbols_by_code = {
            symbol.code: symbol
            for symbol in self.session.scalars(
                select(Symbol).where(
                    Symbol.code.in_([candidate.code for candidate in report.candidates])
                )
            )
        }
        for candidate in report.candidates:
            symbol = symbols_by_code.get(candidate.code)
            self.session.add(
                UniverseAuditDecision(
                    run_id=run.id,
                    symbol_id=symbol.id if symbol is not None else None,
                    original_code=candidate.code,
                    replacement_code=candidate.replacement_code,
                    reason_codes=list(candidate.reason_codes),
                )
            )
        self.session.flush()
        return run

    def list_decisions(self, run_id: int) -> list[UniverseAuditDecision]:
        return list(
            self.session.scalars(
                select(UniverseAuditDecision)
                .where(UniverseAuditDecision.run_id == run_id)
                .order_by(UniverseAuditDecision.original_code)
            )
        )

    def approve_deactivation(
        self,
        *,
        decision_id: int,
        approved_by: str,
    ) -> UniverseAuditDecision:
        decision = self.session.get(UniverseAuditDecision, decision_id)
        if decision is None:
            raise ValueError(f"universe audit decision을 찾을 수 없습니다: {decision_id}")
        if decision.action != "deactivate":
            raise ValueError("deactivate action만 승인할 수 있습니다")
        if decision.status != "pending":
            raise ValueError(f"pending decision만 승인할 수 있습니다: {decision_id}")

        now = datetime.utcnow()
        decision.status = "approved"
        decision.approved_by = approved_by
        decision.approved_at = now

        run = self.session.get(UniverseAuditRun, decision.run_id)
        if run is not None and run.status == "pending":
            run.status = "approved"
            run.approved_by = approved_by
            run.approved_at = now
        self.session.flush()
        return decision

    def apply_approved_deactivations(
        self,
        *,
        run_id: int,
        applied_by: str,
    ) -> UniverseAuditApplyResult:
        run = self.session.get(UniverseAuditRun, run_id)
        if run is None:
            raise ValueError(f"universe audit run을 찾을 수 없습니다: {run_id}")

        decisions = list(
            self.session.scalars(
                select(UniverseAuditDecision)
                .where(
                    UniverseAuditDecision.run_id == run_id,
                    UniverseAuditDecision.status == "approved",
                    UniverseAuditDecision.action == "deactivate",
                )
                .order_by(UniverseAuditDecision.id)
                .with_for_update()
            )
        )
        now = datetime.utcnow()
        applied_count = 0
        for decision in decisions:
            symbol = (
                self.session.get(Symbol, decision.symbol_id)
                if decision.symbol_id is not None
                else None
            )
            if symbol is None or not symbol.is_active:
                continue

            symbol.is_active = False
            symbol.delisted_at = now.date()
            symbol.legacy_state = "deactivated"
            symbol.legacy_reason = ",".join(decision.reason_codes)
            symbol.legacy_audit_run_id = run.id
            decision.status = "applied"
            decision.applied_at = now
            applied_count += 1

        if applied_count:
            run.status = "applied"
            run.applied_by = applied_by
            run.applied_at = now
        self.session.flush()
        return UniverseAuditApplyResult(run_id=run.id, applied_count=applied_count)
