"""Deterministic batch-level data-quality validation.

This module intentionally contains no LLM or provider call.  It evaluates the
persisted evidence from a crawl job and writes structured cases that a future
SAM skill may inspect through a restricted API.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.benchmark import Benchmark
from app.models.benchmark_daily_price import BenchmarkDailyPrice
from app.models.crawl_failure import CrawlFailure
from app.models.crawl_job import CrawlJob
from app.models.crawl_target_result import CrawlTargetResult
from app.models.daily_price import DailyPrice
from app.models.data_quality import ValidationCase, ValidationRun
from app.models.symbol import Symbol
from app.repositories.data_quality_repository import DataQualityRepository
from app.services.rs.calculator import MIN_REQUIRED_PRICES
from app.services.rs.policy import MARKET_BENCHMARKS
from app.services.validation.rules import RuleFinding, inspect_ohlc_row


@dataclass(frozen=True)
class ValidationPolicy:
    mode: str
    validator_version: str
    coverage_warning: Decimal
    coverage_block: Decimal
    stale_warning_lag_days: int
    stale_block_lag_days: int
    extreme_return_threshold: Decimal
    require_benchmark: bool
    min_history_rows: int = MIN_REQUIRED_PRICES

    @classmethod
    def from_settings(cls, settings: Settings | None = None, *, mode: str | None = None):
        settings = settings or get_settings()
        effective_mode = mode or settings.validation_mode
        if effective_mode not in {"report_only", "enforce"}:
            effective_mode = "report_only"
        return cls(
            mode=effective_mode,
            validator_version=settings.validation_version,
            coverage_warning=Decimal(str(settings.validation_coverage_warning)),
            coverage_block=Decimal(str(settings.validation_coverage_block)),
            stale_warning_lag_days=settings.validation_stale_warning_lag_days,
            stale_block_lag_days=settings.validation_stale_block_lag_days,
            extreme_return_threshold=Decimal(
                str(settings.validation_extreme_return_threshold)
            ),
            require_benchmark=settings.validation_require_benchmark,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "validator_version": self.validator_version,
            "coverage_warning": str(self.coverage_warning),
            "coverage_block": str(self.coverage_block),
            "stale_warning_lag_days": self.stale_warning_lag_days,
            "stale_block_lag_days": self.stale_block_lag_days,
            "extreme_return_threshold": str(self.extreme_return_threshold),
            "require_benchmark": self.require_benchmark,
            "min_history_rows": self.min_history_rows,
        }


@dataclass(frozen=True)
class ValidationResult:
    run: ValidationRun
    cases: list[ValidationCase]
    metrics: dict[str, Any]

    @property
    def would_block(self) -> bool:
        return self.run.validation_status in {"blocked", "failed"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run.id,
            "crawl_job_id": self.run.crawl_job_id,
            "trade_date": _json_value(self.run.trade_date),
            "run_kind": self.run.run_kind,
            "validator_version": self.run.validator_version,
            "mode": self.run.mode,
            "validation_status": self.run.validation_status,
            "expected_symbols": self.run.expected_symbols,
            "fresh_symbols": self.run.fresh_symbols,
            "stale_symbols": self.run.stale_symbols,
            "rs_candidate_symbols": self.run.rs_candidate_symbols,
            "coverage_rate": float(self.run.coverage_rate or 0),
            "rs_fresh_input_coverage_rate": float(
                self.run.rs_fresh_input_coverage_rate or 0
            ),
            "counts": {
                "pass": self.run.pass_count,
                "warning": self.run.warning_count,
                "error": self.run.error_count,
                "critical": self.run.critical_count,
            },
            "metrics": self.metrics,
            "cases": [
                {
                    "id": case.id,
                    "subject_type": case.subject_type,
                    "target_key": case.target_key,
                    "trade_date": _json_value(case.trade_date),
                    "rule_id": case.rule_id,
                    "severity": case.severity,
                    "reason_code": case.reason_code,
                    "case_status": case.case_status,
                    "decision": case.decision,
                    "evidence": case.evidence,
                }
                for case in self.cases
            ],
        }


def validate_crawl_job(
    session: Session,
    job_id: int,
    *,
    target_date: date | None = None,
    run_kind: str = "daily",
    mode: str | None = None,
    policy: ValidationPolicy | None = None,
) -> ValidationResult:
    """Validate one persisted crawl job and return its structured audit result."""

    job = session.get(CrawlJob, job_id)
    if job is None:
        raise ValueError(f"CrawlJob with id {job_id} not found")

    policy = policy or ValidationPolicy.from_settings(mode=mode)
    target_records = _target_records(session, job_id)
    target_codes = sorted({record.target_key for record in target_records if record.target_key})
    if not target_codes:
        target_codes = [
            row.code
            for row in session.scalars(
                select(Symbol).where(Symbol.is_active.is_(True), Symbol.symbol_type == "stock")
            )
        ]
    symbols = {
        row.code: row
        for row in session.scalars(select(Symbol).where(Symbol.code.in_(target_codes))).all()
    }
    effective_date = target_date or _resolve_trade_date(session, target_records)

    repository = DataQualityRepository(session)
    run = repository.create_validation_run(
        crawl_job_id=job_id,
        trade_date=effective_date,
        run_kind=run_kind,
        validator_version=policy.validator_version,
        mode=policy.mode,
        policy_snapshot=policy.as_dict(),
    )
    cases: list[ValidationCase] = []
    try:
        if effective_date is None:
            cases.append(
                _add_case(
                    repository,
                    run.id,
                    policy,
                    subject_type="market",
                    rule_id="target_date_resolution",
                    severity="CRITICAL",
                    reason_code="TARGET_DATE_UNRESOLVED",
                    decision="BLOCK",
                    evidence={"job_id": job_id},
                )
            )
            metrics = {"target_date_resolution": "failed"}
            repository.finish_validation_run(
                run,
                trade_date=None,
                expected_symbols=len(target_codes),
                fresh_symbols=0,
                stale_symbols=0,
                rs_candidate_symbols=0,
                pass_count=0,
                warning_count=0,
                error_count=0,
                critical_count=1,
                coverage_rate=Decimal("0"),
                rs_fresh_input_coverage_rate=Decimal("0"),
                validation_status="blocked",
                metrics=metrics,
            )
            return ValidationResult(run=run, cases=cases, metrics=metrics)

        price_rows, price_row_counts = _load_price_rows(session, symbols, effective_date)
        exact_rows = {
            symbol_id: rows[-1]
            for symbol_id, rows in price_rows.items()
            if rows and rows[-1].trade_date == effective_date
        }
        fresh_symbols = 0
        stale_symbols = 0
        rs_candidates = 0
        stale_lags: list[int] = []
        symbol_error_keys: set[str] = set()

        for code in target_codes:
            symbol = symbols.get(code)
            if symbol is None:
                cases.append(
                    _add_case(
                        repository,
                        run.id,
                        policy,
                        subject_type="crawl_target",
                        rule_id="target_symbol_exists",
                        severity="ERROR",
                        reason_code="WRONG_SYMBOL",
                        target_key=code,
                        decision="BLOCK",
                        evidence={"target_key": code},
                    )
                )
                symbol_error_keys.add(code)
                continue

            rows = price_rows.get(symbol.id, [])
            if price_row_counts.get(symbol.id, 0) >= policy.min_history_rows:
                rs_candidates += 1
            if not rows:
                cases.append(
                    _add_case(
                        repository,
                        run.id,
                        policy,
                        subject_type="rs_input",
                        rule_id="persisted_price_presence",
                        severity="ERROR",
                        reason_code="MISSING_ROW",
                        symbol_id=symbol.id,
                        target_key=code,
                        trade_date=effective_date,
                        decision="BLOCK",
                        evidence={"latest_observed_date": None},
                    )
                )
                symbol_error_keys.add(code)
                continue

            latest = rows[-1]
            lag = (effective_date - latest.trade_date).days
            if lag == 0:
                fresh_symbols += 1
            else:
                stale_symbols += 1
                stale_lags.append(lag)
                severity = (
                    "CRITICAL"
                    if lag >= policy.stale_block_lag_days
                    else "WARNING"
                )
                cases.append(
                    _add_case(
                        repository,
                        run.id,
                        policy,
                        subject_type="rs_input",
                        rule_id="rs_input_freshness",
                        severity=severity,
                        reason_code="RS_INPUT_STALE",
                        symbol_id=symbol.id,
                        target_key=code,
                        trade_date=effective_date,
                        decision="BLOCK" if severity == "CRITICAL" else "REVIEW",
                        evidence={
                            "latest_observed_date": latest.trade_date.isoformat(),
                            "target_date": effective_date.isoformat(),
                            "stale_lag_days": lag,
                            "price_row_count": price_row_counts.get(symbol.id, 0),
                        },
                    )
                )
                if severity in {"ERROR", "CRITICAL"}:
                    symbol_error_keys.add(code)

            if latest.trade_date == effective_date:
                for finding in inspect_ohlc_row(latest):
                    cases.append(
                        _add_case(
                            repository,
                            run.id,
                            policy,
                            subject_type="daily_price",
                            symbol_id=symbol.id,
                            target_key=code,
                            trade_date=effective_date,
                            finding=finding,
                        )
                    )
                    if finding.severity in {"ERROR", "CRITICAL"}:
                        symbol_error_keys.add(code)

            if len(rows) >= 2:
                previous, current = rows[-2], rows[-1]
                if previous.close and previous.close > 0:
                    return_rate = abs((current.close / previous.close) - Decimal("1"))
                    if return_rate > policy.extreme_return_threshold:
                        cases.append(
                            _add_case(
                                repository,
                                run.id,
                                policy,
                                subject_type="daily_price",
                                rule_id="extreme_return",
                                severity="WARNING",
                                reason_code="EXTREME_RETURN",
                                symbol_id=symbol.id,
                                target_key=code,
                                trade_date=effective_date,
                                decision="REVIEW",
                                evidence={
                                    "previous_trade_date": previous.trade_date.isoformat(),
                                    "previous_close": str(previous.close),
                                    "current_close": str(current.close),
                                    "return_rate": str(return_rate),
                                    "threshold": str(policy.extreme_return_threshold),
                                },
                            )
                        )

        cases.extend(
            _validate_ingest_failures(
                repository,
                run.id,
                policy,
                session,
                job_id,
                effective_date,
            )
        )
        cases.extend(
            _validate_coverage(
                repository,
                run.id,
                policy,
                target_codes,
                symbols,
                exact_rows,
                fresh_symbols,
                effective_date,
            )
        )
        cases.extend(
            _validate_benchmarks(
                repository,
                run.id,
                policy,
                session,
                effective_date,
            )
        )

        counts = Counter(case.severity for case in cases)
        coverage = _ratio(fresh_symbols, len(target_codes))
        rs_fresh_candidates = sum(
            1
            for code in target_codes
            if symbols.get(code) is not None
            and price_row_counts.get(symbols[code].id, 0) >= policy.min_history_rows
            and price_rows[symbols[code].id][-1].trade_date == effective_date
        )
        rs_coverage = _ratio(rs_fresh_candidates, rs_candidates)
        status = _status_from_counts(counts)
        metrics = _build_metrics(
            cases=cases,
            target_records=target_records,
            fresh_symbols=fresh_symbols,
            stale_symbols=stale_symbols,
            stale_lags=stale_lags,
            rs_fresh_candidates=rs_fresh_candidates,
            target_codes=target_codes,
            symbol_error_keys=symbol_error_keys,
        )
        repository.finish_validation_run(
            run,
            trade_date=effective_date,
            expected_symbols=len(target_codes),
            fresh_symbols=fresh_symbols,
            stale_symbols=stale_symbols,
            rs_candidate_symbols=rs_candidates,
            pass_count=max(len(target_codes) - len(symbol_error_keys), 0),
            warning_count=counts["WARNING"],
            error_count=counts["ERROR"],
            critical_count=counts["CRITICAL"],
            coverage_rate=coverage,
            rs_fresh_input_coverage_rate=rs_coverage,
            validation_status=status,
            metrics=metrics,
        )
        return ValidationResult(run=run, cases=cases, metrics=metrics)
    except Exception as exc:
        repository.finish_validation_run(
            run,
            trade_date=effective_date,
            expected_symbols=len(target_codes),
            fresh_symbols=0,
            stale_symbols=0,
            rs_candidate_symbols=0,
            pass_count=0,
            warning_count=0,
            error_count=1,
            critical_count=0,
            coverage_rate=Decimal("0"),
            rs_fresh_input_coverage_rate=Decimal("0"),
            validation_status="failed",
            metrics={"validator_error": type(exc).__name__, "message": str(exc)[:500]},
        )
        raise


def _target_records(session: Session, job_id: int) -> list[CrawlTargetResult]:
    prices = list(
        session.scalars(
            select(CrawlTargetResult).where(
                CrawlTargetResult.job_id == job_id,
                CrawlTargetResult.step_name == "prices",
            )
        )
    )
    if prices:
        return prices
    return list(
        session.scalars(
            select(CrawlTargetResult).where(
                CrawlTargetResult.job_id == job_id,
                CrawlTargetResult.step_name == "eod",
            )
        )
    )


def _resolve_trade_date(
    session: Session, target_records: list[CrawlTargetResult]
) -> date | None:
    dates = [record.trade_date for record in target_records if record.trade_date is not None]
    if dates:
        return Counter(dates).most_common(1)[0][0]
    benchmark_dates = [
        session.scalar(
            select(func.max(BenchmarkDailyPrice.trade_date))
            .join(Benchmark, Benchmark.id == BenchmarkDailyPrice.benchmark_id)
            .where(Benchmark.benchmark_code == code)
        )
        for code in MARKET_BENCHMARKS.values()
    ]
    benchmark_dates = [value for value in benchmark_dates if value is not None]
    if benchmark_dates:
        return min(benchmark_dates)
    return session.scalar(select(func.max(DailyPrice.trade_date)))


def _load_price_rows(
    session: Session,
    symbols: dict[str, Symbol],
    target_date: date,
) -> tuple[dict[int, list[DailyPrice]], dict[int, int]]:
    ids = [symbol.id for symbol in symbols.values()]
    if not ids:
        return {}, {}
    result: dict[int, list[DailyPrice]] = defaultdict(list)
    counts = {
        symbol_id: count
        for symbol_id, count in session.execute(
            select(DailyPrice.symbol_id, func.count(DailyPrice.id))
            .where(DailyPrice.symbol_id.in_(ids), DailyPrice.trade_date <= target_date)
            .group_by(DailyPrice.symbol_id)
        ).all()
    }
    ranked = (
        select(
            DailyPrice.id.label("price_id"),
            func.row_number()
            .over(
                partition_by=DailyPrice.symbol_id,
                order_by=DailyPrice.trade_date.desc(),
            )
            .label("row_number"),
        )
        .where(DailyPrice.symbol_id.in_(ids), DailyPrice.trade_date <= target_date)
        .subquery()
    )
    rows = session.scalars(
        select(DailyPrice)
        .join(ranked, ranked.c.price_id == DailyPrice.id)
        .where(ranked.c.row_number <= 2)
        .order_by(DailyPrice.symbol_id, DailyPrice.trade_date)
    ).all()
    for row in rows:
        result[row.symbol_id].append(row)
    return result, counts


def _validate_ingest_failures(
    repository: DataQualityRepository,
    run_id: int,
    policy: ValidationPolicy,
    session: Session,
    job_id: int,
    target_date: date,
) -> list[ValidationCase]:
    cases: list[ValidationCase] = []
    failures = session.scalars(
        select(CrawlFailure).where(CrawlFailure.job_id == job_id).order_by(CrawlFailure.id)
    ).all()
    for failure in failures:
        reason = _failure_reason(failure)
        severity = "ERROR" if reason in {"INVALID_PRICE", "INVALID_OHLC"} else "WARNING"
        cases.append(
            _add_case(
                repository,
                run_id,
                policy,
                subject_type="crawl_target",
                rule_id="ingest_failure",
                severity=severity,
                reason_code=reason,
                target_key=failure.target_key,
                trade_date=target_date,
                decision="REVIEW" if severity == "WARNING" else "BLOCK",
                evidence={
                    "target_type": failure.target_type,
                    "error_class": failure.error_class,
                    "error_message": failure.error_message[:1000],
                    "http_status": failure.http_status,
                    "retry_count": failure.retry_count,
                },
            )
        )
    return cases


def _validate_coverage(
    repository: DataQualityRepository,
    run_id: int,
    policy: ValidationPolicy,
    target_codes: list[str],
    symbols: dict[str, Symbol],
    exact_rows: dict[int, DailyPrice],
    fresh_symbols: int,
    target_date: date,
) -> list[ValidationCase]:
    cases: list[ValidationCase] = []
    coverage = _ratio(fresh_symbols, len(target_codes))
    if coverage < policy.coverage_block:
        cases.append(
            _add_case(
                repository,
                run_id,
                policy,
                subject_type="market",
                rule_id="coverage",
                severity="CRITICAL",
                reason_code="COVERAGE_BELOW_POLICY",
                trade_date=target_date,
                decision="BLOCK",
                evidence={
                    "fresh_symbols": fresh_symbols,
                    "expected_symbols": len(target_codes),
                    "coverage_rate": str(coverage),
                    "block_threshold": str(policy.coverage_block),
                },
            )
        )
    elif coverage < policy.coverage_warning:
        cases.append(
            _add_case(
                repository,
                run_id,
                policy,
                subject_type="market",
                rule_id="coverage",
                severity="WARNING",
                reason_code="COVERAGE_BELOW_POLICY",
                trade_date=target_date,
                decision="REVIEW",
                evidence={
                    "fresh_symbols": fresh_symbols,
                    "expected_symbols": len(target_codes),
                    "coverage_rate": str(coverage),
                    "warning_threshold": str(policy.coverage_warning),
                },
            )
        )

    by_market: dict[str, list[str]] = defaultdict(list)
    for code in target_codes:
        symbol = symbols.get(code)
        if symbol:
            by_market[symbol.market].append(code)
    for market, codes in by_market.items():
        fresh = sum(
            1
            for code in codes
            if symbols[code].id in exact_rows
        )
        market_coverage = _ratio(fresh, len(codes))
        if market_coverage < policy.coverage_block:
            cases.append(
                _add_case(
                    repository,
                    run_id,
                    policy,
                    subject_type="market",
                    rule_id="market_coverage",
                    severity="CRITICAL",
                    reason_code="MARKET_WIDE_ANOMALY",
                    target_key=market,
                    trade_date=target_date,
                    decision="BLOCK",
                    evidence={
                        "market": market,
                        "fresh_symbols": fresh,
                        "expected_symbols": len(codes),
                        "coverage_rate": str(market_coverage),
                    },
                )
            )
    return cases


def _validate_benchmarks(
    repository: DataQualityRepository,
    run_id: int,
    policy: ValidationPolicy,
    session: Session,
    target_date: date,
) -> list[ValidationCase]:
    cases: list[ValidationCase] = []
    for market, code in MARKET_BENCHMARKS.items():
        benchmark = session.scalar(
            select(Benchmark).where(Benchmark.benchmark_code == code)
        )
        severity = "CRITICAL" if policy.require_benchmark else "WARNING"
        if benchmark is None:
            cases.append(
                _add_case(
                    repository,
                    run_id,
                    policy,
                    subject_type="benchmark",
                    rule_id="benchmark_presence",
                    severity=severity,
                    reason_code="BENCHMARK_MISSING",
                    target_key=code,
                    trade_date=target_date,
                    decision="BLOCK" if severity == "CRITICAL" else "REVIEW",
                    evidence={"market": market, "benchmark_code": code},
                )
            )
            continue
        row = session.scalar(
            select(BenchmarkDailyPrice).where(
                BenchmarkDailyPrice.benchmark_id == benchmark.id,
                BenchmarkDailyPrice.trade_date == target_date,
            )
        )
        if row is None:
            cases.append(
                _add_case(
                    repository,
                    run_id,
                    policy,
                    subject_type="benchmark",
                    benchmark_id=benchmark.id,
                    rule_id="benchmark_date_alignment",
                    severity=severity,
                    reason_code="BENCHMARK_DATE_MISMATCH",
                    target_key=code,
                    trade_date=target_date,
                    decision="BLOCK" if severity == "CRITICAL" else "REVIEW",
                    evidence={"market": market, "benchmark_code": code},
                )
            )
            continue
        for finding in inspect_ohlc_row(
            row,
            rule_id="benchmark_ohlc",
            allow_null_volume=True,
        ):
            cases.append(
                _add_case(
                    repository,
                    run_id,
                    policy,
                    subject_type="benchmark",
                    benchmark_id=benchmark.id,
                    target_key=code,
                    trade_date=target_date,
                    finding=finding,
                )
            )
    return cases


def _add_case(
    repository: DataQualityRepository,
    run_id: int,
    policy: ValidationPolicy,
    *,
    subject_type: str,
    rule_id: str,
    severity: str | None = None,
    reason_code: str | None = None,
    finding: RuleFinding | None = None,
    evidence: dict[str, Any] | None = None,
    symbol_id: int | None = None,
    benchmark_id: int | None = None,
    target_key: str | None = None,
    trade_date: date | None = None,
    decision: str | None = None,
    case_status: str = "open",
) -> ValidationCase:
    if finding is not None:
        severity = finding.severity
        reason_code = finding.reason_code
        rule_id = finding.rule_id
        evidence = {**finding.evidence, **(evidence or {})}
        decision = finding.decision
        case_status = finding.case_status
    assert severity is not None
    assert reason_code is not None
    return repository.add_case(
        validation_run_id=run_id,
        subject_type=subject_type,
        symbol_id=symbol_id,
        benchmark_id=benchmark_id,
        target_key=target_key,
        trade_date=trade_date,
        rule_id=rule_id,
        severity=severity,
        reason_code=reason_code,
        decision=decision,
        case_status=case_status,
        evidence=evidence,
        validator_version=policy.validator_version,
    )


def _failure_reason(failure: CrawlFailure) -> str:
    message = f"{failure.error_class} {failure.error_message}".lower()
    if "corporate_action" in failure.target_type.lower() or "corporate action" in message:
        return "CORPORATE_ACTION_SUSPECTED"
    if "empty" in message or "no price" in message or "no data" in message:
        return "NAVER_EMPTY_RESPONSE"
    if "positive" in message or "price" in message and "validation" in message:
        return "INVALID_PRICE"
    if "ohlc" in message or "high" in message and "low" in message:
        return "INVALID_OHLC"
    return "NAVER_CRAWL_ERROR"


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        return Decimal("0")
    return (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.000001"))


def _status_from_counts(counts: Counter[str]) -> str:
    if counts["CRITICAL"] or counts["ERROR"]:
        return "blocked"
    if counts["WARNING"]:
        return "passed_with_warnings"
    return "passed"


def _build_metrics(
    *,
    cases: list[ValidationCase],
    target_records: list[CrawlTargetResult],
    fresh_symbols: int,
    stale_symbols: int,
    stale_lags: list[int],
    rs_fresh_candidates: int,
    target_codes: list[str],
    symbol_error_keys: set[str],
) -> dict[str, Any]:
    reason_counts = Counter(case.reason_code for case in cases)
    rule_counts = Counter(case.rule_id for case in cases)
    status_counts = Counter(record.status for record in target_records)
    return {
        "target_events": len(target_records),
        "target_status_counts": dict(status_counts),
        "unique_target_symbols": len(target_codes),
        "unique_error_symbols": len(symbol_error_keys),
        "fresh_symbols": fresh_symbols,
        "stale_symbols": stale_symbols,
        "stale_lag_days": {
            "min": min(stale_lags) if stale_lags else None,
            "max": max(stale_lags) if stale_lags else None,
            "avg": (sum(stale_lags) / len(stale_lags) if stale_lags else None),
        },
        "rs_fresh_candidates": rs_fresh_candidates,
        "case_count": len(cases),
        "reason_counts": dict(reason_counts),
        "rule_counts": dict(rule_counts),
    }


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    return value.isoformat() if hasattr(value, "isoformat") else value
