"""Persistence helpers for validation and RS lineage records."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.data_quality import (
    OhlcCorrection,
    OhlcExclusion,
    RsInputSnapshot,
    RsRun,
    ValidationCase,
    ValidationRun,
)


class DataQualityRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_validation_run(
        self,
        *,
        crawl_job_id: int | None,
        trade_date: date | None,
        run_kind: str,
        validator_version: str,
        mode: str,
        policy_snapshot: dict[str, Any],
    ) -> ValidationRun:
        run = ValidationRun(
            crawl_job_id=crawl_job_id,
            trade_date=trade_date,
            run_kind=run_kind,
            validator_version=validator_version,
            mode=mode,
            policy_snapshot=policy_snapshot,
            validation_status="running",
        )
        self.session.add(run)
        self.session.flush()
        return run

    def add_case(
        self,
        *,
        validation_run_id: int,
        subject_type: str,
        rule_id: str,
        severity: str,
        reason_code: str,
        evidence: dict[str, Any] | None = None,
        symbol_id: int | None = None,
        benchmark_id: int | None = None,
        target_key: str | None = None,
        trade_date: date | None = None,
        decision: str | None = None,
        case_status: str = "open",
        confidence: Decimal | None = None,
        validator_version: str = "1.0.0",
    ) -> ValidationCase:
        case = ValidationCase(
            validation_run_id=validation_run_id,
            subject_type=subject_type,
            symbol_id=symbol_id,
            benchmark_id=benchmark_id,
            target_key=target_key,
            trade_date=trade_date,
            rule_id=rule_id,
            severity=severity,
            reason_code=reason_code,
            case_status=case_status,
            decision=decision,
            confidence=confidence,
            evidence=evidence or {},
            validator_version=validator_version,
            resolved_at=(datetime.utcnow() if case_status == "auto_resolved" else None),
        )
        self.session.add(case)
        return case

    def finish_validation_run(
        self,
        run: ValidationRun,
        *,
        trade_date: date | None,
        expected_symbols: int,
        fresh_symbols: int,
        stale_symbols: int,
        rs_candidate_symbols: int,
        pass_count: int,
        warning_count: int,
        error_count: int,
        critical_count: int,
        coverage_rate: Decimal,
        rs_fresh_input_coverage_rate: Decimal,
        validation_status: str,
        metrics: dict[str, Any],
    ) -> ValidationRun:
        run.trade_date = trade_date
        run.expected_symbols = expected_symbols
        run.fresh_symbols = fresh_symbols
        run.stale_symbols = stale_symbols
        run.rs_candidate_symbols = rs_candidate_symbols
        run.pass_count = pass_count
        run.warning_count = warning_count
        run.error_count = error_count
        run.critical_count = critical_count
        run.coverage_rate = coverage_rate
        run.rs_fresh_input_coverage_rate = rs_fresh_input_coverage_rate
        run.validation_status = validation_status
        run.metrics = metrics
        run.completed_at = datetime.utcnow()
        self.session.flush()
        return run

    def get_validation_run(self, run_id: int) -> ValidationRun | None:
        return self.session.get(ValidationRun, run_id)

    def latest_validation_run(
        self,
        *,
        trade_date: date | None = None,
        crawl_job_id: int | None = None,
    ) -> ValidationRun | None:
        stmt = select(ValidationRun).order_by(desc(ValidationRun.created_at)).limit(1)
        if trade_date is not None:
            stmt = stmt.where(ValidationRun.trade_date == trade_date)
        if crawl_job_id is not None:
            stmt = stmt.where(ValidationRun.crawl_job_id == crawl_job_id)
        return self.session.scalar(stmt)

    def approve_correction(self, correction_id: int) -> OhlcCorrection:
        correction = self.session.get(OhlcCorrection, correction_id)
        if correction is None:
            raise ValueError(f"OhlcCorrection with id {correction_id} not found")
        correction.status = "APPROVED"
        correction.approved_at = datetime.utcnow()
        self.session.flush()
        return correction

    def approve_exclusion(self, exclusion_id: int) -> OhlcExclusion:
        exclusion = self.session.get(OhlcExclusion, exclusion_id)
        if exclusion is None:
            raise ValueError(f"OhlcExclusion with id {exclusion_id} not found")
        exclusion.status = "APPROVED"
        exclusion.approved_at = datetime.utcnow()
        self.session.flush()
        return exclusion

    def create_rs_run(
        self,
        *,
        validation_run_id: int | None,
        trade_date: date,
        input_policy_version: str,
        mode: str,
    ) -> RsRun:
        run = RsRun(
            validation_run_id=validation_run_id,
            trade_date=trade_date,
            input_policy_version=input_policy_version,
            mode=mode,
            status="running",
        )
        self.session.add(run)
        self.session.flush()
        return run

    def add_rs_input_snapshot(
        self,
        *,
        rs_run_id: int,
        symbol_id: int,
        target_date: date,
        input_trade_date: date | None,
        stale_lag_days: int | None,
        input_status: str,
        price_row_count: int,
        price_hash: str | None,
    ) -> RsInputSnapshot:
        snapshot = RsInputSnapshot(
            rs_run_id=rs_run_id,
            symbol_id=symbol_id,
            target_date=target_date,
            input_trade_date=input_trade_date,
            stale_lag_days=stale_lag_days,
            input_status=input_status,
            price_row_count=price_row_count,
            price_hash=price_hash,
        )
        self.session.add(snapshot)
        return snapshot

    def finish_rs_run(
        self,
        run: RsRun,
        *,
        status: str,
        symbol_count: int,
        snapshot_hash: str | None = None,
        error_message: str | None = None,
    ) -> RsRun:
        run.status = status
        run.symbol_count = symbol_count
        run.snapshot_hash = snapshot_hash
        run.error_message = error_message
        run.completed_at = datetime.utcnow()
        self.session.flush()
        return run
