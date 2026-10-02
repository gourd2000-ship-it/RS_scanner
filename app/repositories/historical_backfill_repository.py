"""Repository for frozen historical backfill manifests and target checkpoints."""

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.historical_backfill_run import HistoricalBackfillRun, HistoricalBackfillTargetState

if TYPE_CHECKING:
    from app.services.historical_backfill import HistoricalBackfillPlan


class HistoricalBackfillRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_or_resume(self, run_id: str, plan: "HistoricalBackfillPlan") -> tuple[HistoricalBackfillRun, bool]:
        existing = self.session.scalar(
            select(HistoricalBackfillRun)
            .options(selectinload(HistoricalBackfillRun.targets))
            .where(HistoricalBackfillRun.run_id == run_id)
        )
        if existing is not None:
            if existing.manifest_hash != plan.manifest_hash:
                raise ValueError("run_id has a frozen plan; resume settings or targets differ")
            return existing, False

        run = HistoricalBackfillRun(
            run_id=run_id,
            manifest_hash=plan.manifest_hash,
            manifest=plan.serialized(),
            range_start=plan.start,
            range_end=plan.end,
            provider=plan.provider,
            adjustment_type=plan.adjustment_type,
            base_date=plan.base_date,
            request_budget=plan.request_budget,
            dry_run=plan.dry_run,
        )
        for target in plan.targets:
            expected_dates = [value.isoformat() for value in target.expected_dates]
            run.targets.append(HistoricalBackfillTargetState(
                instrument_id=target.instrument_id,
                symbol_id=target.symbol_id,
                provider_code=target.provider_code,
                market=target.market,
                expected_dates=expected_dates,
                remaining_dates=expected_dates.copy(),
            ))
        self.session.add(run)
        self.session.flush()
        return run, True

    def get_run(self, run_id: str) -> HistoricalBackfillRun | None:
        return self.session.scalar(
            select(HistoricalBackfillRun)
            .options(selectinload(HistoricalBackfillRun.targets))
            .where(HistoricalBackfillRun.run_id == run_id)
        )

    def extend_request_budget(self, *, run_id: str, additional_requests: int) -> HistoricalBackfillRun:
        """동일한 frozen manifest의 재개 run에만 승인된 요청 한도를 추가한다."""
        if additional_requests < 1:
            raise ValueError("additional request budget must be positive")
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(f"backfill run을 찾을 수 없습니다: {run_id}")
        if run.dry_run:
            raise ValueError("dry-run에는 request budget을 추가할 수 없습니다")
        run.request_budget += additional_requests
        self.session.flush()
        return run

    def mark_target_progress(
        self, *, run_id: str, instrument_id: int, confirmed_dates: list[date], market: str | None = None, retry_count: int = 0
    ) -> HistoricalBackfillTargetState:
        target = self._target(run_id, instrument_id, market)
        expected = set(target.expected_dates)
        completed = set(target.confirmed_dates)
        completed.update(value.isoformat() for value in confirmed_dates if value.isoformat() in expected)
        target.confirmed_dates = sorted(completed)
        target.remaining_dates = [value for value in target.expected_dates if value not in completed]
        parsed = [date.fromisoformat(value) for value in target.confirmed_dates]
        target.confirmed_from = min(parsed) if parsed else None
        target.confirmed_through = max(parsed) if parsed else None
        target.attempt_count += 1
        target.retry_count += retry_count
        target.failure_reason = None
        target.failure_evidence = {}
        target.status = "completed" if not target.remaining_dates else "running"
        self.session.flush()
        return target

    def mark_target_failure(
        self, *, run_id: str, instrument_id: int, reason: str, market: str | None = None, evidence: dict | None = None, retry_count: int = 0
    ) -> HistoricalBackfillTargetState:
        target = self._target(run_id, instrument_id, market)
        target.attempt_count += 1
        target.retry_count += retry_count
        target.status = "failed"
        target.failure_reason = reason
        target.failure_evidence = evidence or {}
        self.session.flush()
        return target

    def mark_target_collection_complete(
        self, *, run_id: str, instrument_id: int, market: str | None = None
    ) -> HistoricalBackfillTargetState:
        """Finish source collection without pretending missing dates were observed.

        ``remaining_dates`` deliberately remains intact: BT07 later classifies
        those expected-but-unobserved dates as closures, suspensions, provider
        gaps, or other evidence-backed cases.  Completion here means that the
        provider pagination reached a normal terminal boundary and should not
        be fetched again merely to fill an absence it already reported.
        """
        target = self._target(run_id, instrument_id, market)
        target.status = "completed"
        self.session.flush()
        return target

    def _target(self, run_id: str, instrument_id: int, market: str | None) -> HistoricalBackfillTargetState:
        statement = select(HistoricalBackfillTargetState).join(HistoricalBackfillRun).where(
            HistoricalBackfillRun.run_id == run_id,
            HistoricalBackfillTargetState.instrument_id == instrument_id,
        )
        if market is not None:
            statement = statement.where(HistoricalBackfillTargetState.market == market)
        targets = list(self.session.scalars(statement))
        target = targets[0] if len(targets) == 1 else None
        if target is None:
            raise KeyError(f"missing or ambiguous target {instrument_id} in run {run_id}")
        return target
