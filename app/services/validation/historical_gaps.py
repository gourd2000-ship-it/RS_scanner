"""Deterministic BT07 period coverage and missing-price classification."""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.symbol import Symbol
from app.repositories.data_quality_repository import DataQualityRepository
from app.services.historical_universe import HistoricalUniverseManifest


@dataclass(frozen=True)
class BackfillOutcome:
    reason: str
    evidence: dict


@dataclass(frozen=True)
class HistoricalGapCase:
    instrument_id: int
    market: str
    reason_code: str
    severity: str
    dates: tuple[date, ...]
    evidence: dict


@dataclass(frozen=True)
class HistoricalCoverage:
    market: str
    year: int
    delisted: bool
    membership_numerator: int | None
    membership_denominator: int | None
    universe_numerator: int
    universe_denominator: int
    price_numerator: int
    price_denominator: int
    valid_price_numerator: int
    valid_price_denominator: int


@dataclass(frozen=True)
class HistoricalGapResult:
    cases: tuple[HistoricalGapCase, ...]
    coverage: tuple[HistoricalCoverage, ...]
    excluded_date_reasons: dict[str, int]
    validator_version: str


def assess_historical_gaps(
    manifest: HistoricalUniverseManifest,
    *,
    observed_dates: set[tuple[int, date]],
    valid_dates: set[tuple[int, date]],
    outcomes: dict[int, BackfillOutcome] | None = None,
    delisted_instrument_ids: set[int] | None = None,
    is_trading_day: Callable[[date], bool],
    validator_version: str = "historical-gaps-v1",
) -> HistoricalGapResult:
    """Compare the frozen target manifest to price presence without imputation."""
    outcomes = outcomes or {}
    delisted_instrument_ids = delisted_instrument_ids or set()
    cases: list[HistoricalGapCase] = []
    expected_by_subject: dict[tuple[int, str, str], list[date]] = {}
    for entry in manifest.entries:
        if entry.price_expectation != "expected":
            if entry.price_expectation == "outside_trading_interval":
                cases.append(HistoricalGapCase(
                    instrument_id=entry.instrument_id, market=entry.market,
                    reason_code="confirmed_suspension", severity="info", dates=(entry.trade_date,),
                    evidence={"trading_status": entry.trading_status, "price_expectation": entry.price_expectation},
                ))
            continue
        if (entry.instrument_id, entry.trade_date) not in observed_dates:
            outcome = outcomes.get(entry.instrument_id)
            reason = outcome.reason if outcome is not None else "expected_missing"
            expected_by_subject.setdefault((entry.instrument_id, entry.market, reason), []).append(entry.trade_date)

    for (instrument_id, market, reason), dates in expected_by_subject.items():
        for contiguous in _contiguous_ranges(sorted(dates)):
            outcome = outcomes.get(instrument_id)
            evidence = dict(outcome.evidence) if outcome is not None else {}
            evidence.update({
                "range": [contiguous[0].isoformat(), contiguous[-1].isoformat()],
                "expected_date_count": len(contiguous),
                "membership_completeness": manifest.membership_completeness,
            })
            cases.append(HistoricalGapCase(
                instrument_id=instrument_id, market=market, reason_code=reason,
                severity=_severity(reason), dates=tuple(contiguous), evidence=evidence,
            ))

    coverage = _coverage(manifest, observed_dates, valid_dates, delisted_instrument_ids)
    return HistoricalGapResult(
        cases=tuple(sorted(cases, key=lambda item: (item.instrument_id, item.dates[0], item.reason_code))),
        coverage=tuple(coverage),
        excluded_date_reasons=_excluded_dates(manifest, is_trading_day),
        validator_version=validator_version,
    )


def persist_historical_gap_result(
    session: Session,
    result: HistoricalGapResult,
    *,
    policy_snapshot: dict | None = None,
) -> int:
    """Store replayable cases; no canonical price row is changed by validation."""
    repository = DataQualityRepository(session)
    run = repository.create_validation_run(
        crawl_job_id=None, trade_date=None, run_kind="historical_gap",
        validator_version=result.validator_version, mode="report_only",
        policy_snapshot=policy_snapshot or {},
    )
    symbols = {
        row.instrument_id: row.id
        for row in session.scalars(select(Symbol).where(Symbol.instrument_id.is_not(None)))
    }
    for case in result.cases:
        repository.add_case(
            validation_run_id=run.id, subject_type="historical_price", symbol_id=symbols.get(case.instrument_id),
            target_key=str(case.instrument_id), trade_date=case.dates[0], rule_id="historical_price_coverage",
            severity=case.severity, reason_code=case.reason_code,
            evidence={**case.evidence, "dates": [value.isoformat() for value in case.dates]},
            validator_version=result.validator_version,
        )
    repository.finish_validation_run(
        run, trade_date=None, expected_symbols=0, fresh_symbols=0, stale_symbols=0,
        rs_candidate_symbols=0, pass_count=0,
        warning_count=sum(case.severity == "warning" for case in result.cases),
        error_count=sum(case.severity == "error" for case in result.cases),
        critical_count=0, coverage_rate=_coverage_rate(result.coverage),
        rs_fresh_input_coverage_rate=_coverage_rate(result.coverage),
        validation_status="completed", metrics={
            "coverage": [row.__dict__ for row in result.coverage],
            "excluded_date_reasons": result.excluded_date_reasons,
        },
    )
    return run.id


def _coverage(
    manifest: HistoricalUniverseManifest,
    observed_dates: set[tuple[int, date]],
    valid_dates: set[tuple[int, date]],
    delisted: set[int],
) -> list[HistoricalCoverage]:
    groups: dict[tuple[str, int, bool], list] = {}
    for entry in manifest.entries:
        groups.setdefault((entry.market, entry.trade_date.year, entry.instrument_id in delisted), []).append(entry)
    rows: list[HistoricalCoverage] = []
    for (market, year, is_delisted), entries in sorted(groups.items()):
        expected = [entry for entry in entries if entry.price_expectation == "expected"]
        price_numerator = sum((entry.instrument_id, entry.trade_date) in observed_dates for entry in expected)
        valid_numerator = sum((entry.instrument_id, entry.trade_date) in valid_dates for entry in expected)
        membership_denominator = len(entries) if manifest.membership_completeness is not None else None
        rows.append(HistoricalCoverage(
            market=market, year=year, delisted=is_delisted,
            membership_numerator=(len(entries) if membership_denominator is not None else None),
            membership_denominator=membership_denominator,
            universe_numerator=len(entries), universe_denominator=len(entries),
            price_numerator=price_numerator, price_denominator=len(expected),
            valid_price_numerator=valid_numerator, valid_price_denominator=len(expected),
        ))
    return rows


def _contiguous_ranges(dates: list[date]) -> list[list[date]]:
    ranges: list[list[date]] = []
    for value in dates:
        if not ranges or (value - ranges[-1][-1]).days > 3:
            ranges.append([value])
        else:
            ranges[-1].append(value)
    return ranges


def _severity(reason: str) -> str:
    if reason in {"fetch_failed", "provider_unsupported"}:
        return "warning"
    if reason == "confirmed_suspension":
        return "info"
    return "error"


def _excluded_dates(manifest: HistoricalUniverseManifest, is_trading_day: Callable[[date], bool]) -> dict[str, int]:
    counts: dict[str, int] = {}
    day = manifest.request.start
    while day <= manifest.request.end:
        if not is_trading_day(day):
            counts["holiday_or_non_trading"] = counts.get("holiday_or_non_trading", 0) + 1
        day += timedelta(days=1)
    return counts


def _coverage_rate(rows: Iterable[HistoricalCoverage]):
    from decimal import Decimal

    numerator = sum(row.valid_price_numerator for row in rows)
    denominator = sum(row.valid_price_denominator for row in rows)
    return Decimal(numerator) / Decimal(denominator) if denominator else Decimal("0")
