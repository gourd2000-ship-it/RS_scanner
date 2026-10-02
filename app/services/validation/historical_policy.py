"""Versioned historical anomaly rules with evidence-based exceptions."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_quality import CorporateAction, OhlcExclusion, ValidationCase
from app.repositories.data_quality_repository import DataQualityRepository
from app.schemas.market_data import DailyPricePayload
from app.services.validation.rules import inspect_ohlc_row


@dataclass(frozen=True)
class HistoricalValidationPolicy:
    version: str
    extreme_return_threshold: Decimal = Decimal("0.30")

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "extreme_return_threshold": str(self.extreme_return_threshold),
            "liquidation_exception": "evidence_only_no_auto_exclusion",
            "price_limit_policy": "no_auto_exclusion",
        }


@dataclass(frozen=True)
class HistoricalAnomalyResult:
    validation_run_id: int
    cases: tuple[ValidationCase, ...]
    replay_hash: str


def validate_historical_prices(
    session: Session,
    *,
    symbol_id: int,
    rows: Iterable[DailyPricePayload],
    policy: HistoricalValidationPolicy,
    trading_status_by_date: dict[date, str] | None = None,
) -> HistoricalAnomalyResult:
    """Evaluate rows without changing canonical values or auto-approving cleanup."""
    ordered = sorted(rows, key=lambda row: row.trade_date)
    statuses = trading_status_by_date or {}
    repository = DataQualityRepository(session)
    run = repository.create_validation_run(
        crawl_job_id=None, trade_date=ordered[-1].trade_date if ordered else None,
        run_kind="historical_anomaly", validator_version=policy.version,
        mode="report_only", policy_snapshot=policy.as_dict(),
    )
    cases: list[ValidationCase] = []
    actions = {
        action.event_date: action
        for action in session.scalars(select(CorporateAction).where(CorporateAction.symbol_id == symbol_id))
    }
    for index, row in enumerate(ordered):
        for finding in inspect_ohlc_row(row, rule_id="historical_ohlc"):
            case = repository.add_case(
                validation_run_id=run.id, subject_type="historical_price", symbol_id=symbol_id,
                target_key=str(symbol_id), trade_date=row.trade_date, rule_id=finding.rule_id,
                severity=finding.severity.lower(), reason_code=finding.reason_code,
                decision="PROPOSE_EXCLUSION", case_status="open", evidence={
                    **finding.evidence, "policy_version": policy.version,
                }, validator_version=policy.version,
            )
            session.flush()
            _propose_exclusion(session, symbol_id=symbol_id, trade_date=row.trade_date, case_id=case.id, reason=finding.reason_code)
            cases.append(case)
        if index == 0 or ordered[index - 1].close <= 0 or row.close <= 0:
            continue
        previous = ordered[index - 1]
        return_rate = (row.close / previous.close) - Decimal("1")
        expected_percent = return_rate * Decimal("100")
        if _sign_convention(row.change_rate, expected_percent):
            cases.append(repository.add_case(
                validation_run_id=run.id, subject_type="historical_price", symbol_id=symbol_id,
                target_key=str(symbol_id), trade_date=row.trade_date, rule_id="provider_change_rate",
                severity="warning", reason_code="PROVIDER_SIGN_CONVENTION", decision="REVIEW",
                evidence={"provider_change_rate": str(row.change_rate), "calculated_percent": str(expected_percent), "policy_version": policy.version},
                validator_version=policy.version,
            ))
        if abs(return_rate) > policy.extreme_return_threshold:
            action = actions.get(row.trade_date)
            status = statuses.get(row.trade_date)
            if action is not None:
                cases.append(repository.add_case(
                    validation_run_id=run.id, subject_type="historical_price", symbol_id=symbol_id,
                    target_key=str(symbol_id), trade_date=row.trade_date, rule_id="historical_extreme_return",
                    severity="info", reason_code="CORPORATE_ACTION_EXPLAINED", decision="KEEP",
                    evidence={"event_type": action.event_type, "action_source": action.source, "return_rate": str(return_rate), "policy_version": policy.version},
                    validator_version=policy.version,
                ))
            if status == "liquidation_trading":
                cases.append(repository.add_case(
                    validation_run_id=run.id, subject_type="historical_price", symbol_id=symbol_id,
                    target_key=str(symbol_id), trade_date=row.trade_date, rule_id="historical_extreme_return",
                    severity="info", reason_code="LIQUIDATION_EXCEPTION", decision="KEEP",
                    evidence={"trading_status": status, "return_rate": str(return_rate), "policy_version": policy.version},
                    validator_version=policy.version,
                ))
            if action is None and status != "liquidation_trading":
                cases.append(repository.add_case(
                    validation_run_id=run.id, subject_type="historical_price", symbol_id=symbol_id,
                    target_key=str(symbol_id), trade_date=row.trade_date, rule_id="historical_extreme_return",
                    severity="warning", reason_code="EXTREME_RETURN", decision="REVIEW",
                    evidence={"return_rate": str(return_rate), "threshold": str(policy.extreme_return_threshold), "policy_version": policy.version},
                    validator_version=policy.version,
                ))
    session.flush()
    repository.finish_validation_run(
        run, trade_date=run.trade_date, expected_symbols=1, fresh_symbols=1, stale_symbols=0,
        rs_candidate_symbols=0, pass_count=int(not cases),
        warning_count=sum(case.severity == "warning" for case in cases),
        error_count=sum(case.severity == "error" for case in cases), critical_count=0,
        coverage_rate=Decimal("1"), rs_fresh_input_coverage_rate=Decimal("1"),
        validation_status="completed", metrics={"replay_hash": _replay_hash(cases), "policy": policy.as_dict()},
    )
    return HistoricalAnomalyResult(validation_run_id=run.id, cases=tuple(cases), replay_hash=_replay_hash(cases))


def _propose_exclusion(session: Session, *, symbol_id: int, trade_date: date, case_id: int, reason: str) -> None:
    existing = session.scalar(select(OhlcExclusion).where(OhlcExclusion.symbol_id == symbol_id, OhlcExclusion.trade_date == trade_date))
    if existing is None:
        session.add(OhlcExclusion(
            symbol_id=symbol_id, trade_date=trade_date, reason_code=reason,
            validation_case_id=case_id, status="PROPOSED",
        ))


def _sign_convention(reported: Decimal, expected_percent: Decimal) -> bool:
    return expected_percent != 0 and reported == -expected_percent


def _replay_hash(cases: Iterable[ValidationCase]) -> str:
    material = [
        {"rule_id": case.rule_id, "severity": case.severity, "reason_code": case.reason_code, "trade_date": case.trade_date.isoformat() if case.trade_date else None, "evidence": case.evidence}
        for case in cases
    ]
    return sha256(json.dumps(material, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
