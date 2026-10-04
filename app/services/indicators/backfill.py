"""Operator-facing, bounded historical EMA planning and application.

Planning selects the exact policy-bound inputs and performs the pure Decimal
calculation, but never invokes a repository write method.  Application delegates
each target to :class:`EmaCalculationService`; its existing input-history check
makes a repeated or resumed plan reuse completed immutable runs.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
import json
from math import ceil
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.market_calendar import krx_market_day_status
from app.models.data_quality import PriceObservation
from app.models.indicator import PriceObservationIdentitySnapshot
from app.models.instrument import ProviderSymbol
from app.repositories.indicator_repository import IndicatorRepository
from app.services.indicators.calculation_service import EmaCalculationOutcome, EmaCalculationService
from app.services.indicators.contracts import (
    EMA_PERIODS,
    EmaCalculationResult,
    EmaInputRow,
    EmaSourcePolicy,
    EmaStatus,
    InputHistoryKind,
    canonical_json,
    compare_input_histories,
)
from app.services.indicators.ema import compute_ema
from app.services.indicators.input_selector import EmaInputSelector


# These are conservative planning estimates, not database quotas.  The values
# include indexes/row headers and keep the operator report independent of a
# particular PostgreSQL table-size sample.
_ESTIMATED_INPUT_SNAPSHOT_BYTES = 1_024
_ESTIMATED_VALUE_BYTES = 192
_ESTIMATED_VALUES_PER_SECOND = 20_000


@dataclass(frozen=True)
class EmaHistoricalBackfillRequest:
    """The complete deterministic selection contract for an operator run."""

    start: date
    end: date
    policy: EmaSourcePolicy
    instrument_ids: tuple[int, ...] = ()
    chunk_size: int = 50

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("EMA backfill end must not be earlier than start")
        if self.chunk_size < 1 or self.chunk_size > 500:
            raise ValueError("EMA backfill chunk_size must be between 1 and 500")
        normalized_ids = tuple(sorted(set(self.instrument_ids)))
        if any(value <= 0 for value in normalized_ids):
            raise ValueError("EMA backfill instrument IDs must be positive")
        object.__setattr__(self, "instrument_ids", normalized_ids)

    def report_material(self) -> dict[str, Any]:
        return _json_ready({
            "start": self.start,
            "end": self.end,
            "policy": self.policy.fingerprint_material(),
            "instrument_ids": self.instrument_ids,
            "chunk_size": self.chunk_size,
        })


@dataclass(frozen=True)
class EmaHistoricalBackfillTarget:
    """A calculated, non-persisted plan for one historical instrument."""

    instrument_id: int
    trade_dates: tuple[date, ...]
    rows: tuple[EmaInputRow, ...]
    result: EmaCalculationResult
    action: str

    def report_material(self) -> dict[str, Any]:
        values_by_period: dict[int, list] = {period: [] for period in EMA_PERIODS}
        for value in self.result.values:
            values_by_period[value.period].append(value)
        first_available = {
            str(period): next(
                (value.trade_date for value in values_by_period[period] if value.status is EmaStatus.AVAILABLE),
                None,
            )
            for period in EMA_PERIODS
        }
        status_counts = Counter(value.status.value for value in self.result.values)
        return {
            "instrument_id": self.instrument_id,
            "range": {
                "start": self.trade_dates[0].isoformat() if self.trade_dates else None,
                "end": self.trade_dates[-1].isoformat() if self.trade_dates else None,
            },
            "expected_trade_dates": len(self.trade_dates),
            "action": self.action,
            "input_hash": self.result.input_hash,
            "result_hash": self.result.result_hash,
            "first_available": {
                period: trade_date.isoformat() if trade_date is not None else None
                for period, trade_date in first_available.items()
            },
            "warming_up_rows": status_counts[EmaStatus.WARMING_UP.value],
            "data_unavailable_rows": status_counts[EmaStatus.DATA_UNAVAILABLE.value],
            "available_rows": status_counts[EmaStatus.AVAILABLE.value],
        }


@dataclass(frozen=True)
class EmaHistoricalBackfillPlan:
    request: EmaHistoricalBackfillRequest
    targets: tuple[EmaHistoricalBackfillTarget, ...]

    def report(self) -> dict[str, Any]:
        target_reports = [target.report_material() for target in self.targets]
        counts = Counter()
        for target in target_reports:
            counts["input_rows"] += target["expected_trade_dates"]
            counts["indicator_value_rows"] += target["expected_trade_dates"] * len(EMA_PERIODS)
            counts["warming_up_rows"] += target["warming_up_rows"]
            counts["data_unavailable_rows"] += target["data_unavailable_rows"]
            counts["available_rows"] += target["available_rows"]
            counts["rebuild_targets"] += target["action"] == "rebuild"
        counts["targets"] = len(target_reports)
        input_rows = counts["input_rows"]
        value_rows = counts["indicator_value_rows"]
        storage_bytes = input_rows * _ESTIMATED_INPUT_SNAPSHOT_BYTES + value_rows * _ESTIMATED_VALUE_BYTES
        report_without_hash = {
            "schema_version": 1,
            "mode": "dry_run_plan",
            "request": self.request.report_material(),
            "counts": {
                "targets": counts["targets"],
                "input_rows": input_rows,
                "indicator_value_rows": value_rows,
                "warming_up_rows": counts["warming_up_rows"],
                "data_unavailable_rows": counts["data_unavailable_rows"],
                "available_rows": counts["available_rows"],
                "rebuild_targets": counts["rebuild_targets"],
            },
            "estimate": {
                "input_snapshot_rows": input_rows,
                "indicator_value_rows": value_rows,
                "storage_bytes": storage_bytes,
                "estimated_seconds": ceil(value_rows / _ESTIMATED_VALUES_PER_SECOND),
            },
            "targets": target_reports,
        }
        from hashlib import sha256

        return {
            **report_without_hash,
            "report_hash": sha256(canonical_json(report_without_hash).encode("utf-8")).hexdigest(),
        }


@dataclass(frozen=True)
class EmaHistoricalBackfillApplication:
    """The concise result of an explicit apply or resumed apply."""

    report_hash: str
    attempted: int
    created: int
    reused: int
    chunks: int
    outcomes: tuple[dict[str, Any], ...]

    def report(self) -> dict[str, Any]:
        material = {
            "schema_version": 1,
            "mode": "apply",
            "plan_report_hash": self.report_hash,
            "attempted": self.attempted,
            "created": self.created,
            "reused": self.reused,
            "chunks": self.chunks,
            "outcomes": list(self.outcomes),
        }
        from hashlib import sha256

        return {
            **material,
            "report_hash": sha256(canonical_json(material).encode("utf-8")).hexdigest(),
        }


class EmaHistoricalBackfillService:
    """Create read-only plans, then apply a bounded plan one target at a time."""

    def __init__(
        self,
        session: Session,
        *,
        is_trading_day: Callable[[date], bool] | None = None,
    ) -> None:
        self.session = session
        self.selector = EmaInputSelector(session)
        self.repository = IndicatorRepository(session)
        self.is_trading_day = is_trading_day or (lambda value: krx_market_day_status(value).is_open)

    def plan(self, request: EmaHistoricalBackfillRequest) -> EmaHistoricalBackfillPlan:
        """Build a complete report without adding, flushing, or committing rows."""
        dates = tuple(_trading_dates(request.start, request.end, self.is_trading_day))
        if not dates:
            raise ValueError("EMA backfill range has no KRX trading dates")
        instrument_ids = request.instrument_ids or self._discover_instrument_ids(request)
        targets = tuple(
            self._plan_target(instrument_id=instrument_id, trade_dates=dates, request=request)
            for instrument_id in instrument_ids
        )
        return EmaHistoricalBackfillPlan(request=request, targets=targets)

    def streaming_plan_report(self, request: EmaHistoricalBackfillRequest) -> dict[str, Any]:
        """Build the operator report one instrument at a time.

        The historical production range contains millions of observations.  A
        normal :meth:`plan` is useful for a bounded sample, but retaining every
        ``EmaInputRow`` and ``EmaValue`` for the whole market would turn a
        read-only dry-run into a multi-gigabyte allocation.  This path keeps
        only the compact per-instrument report rows.
        """
        dates = tuple(_trading_dates(request.start, request.end, self.is_trading_day))
        if not dates:
            raise ValueError("EMA backfill range has no KRX trading dates")
        instrument_ids = request.instrument_ids or self._discover_instrument_ids(request)
        target_reports: list[dict[str, Any]] = []
        counts = Counter()
        for instrument_id in instrument_ids:
            target = self._plan_target(
                instrument_id=instrument_id,
                trade_dates=dates,
                request=request,
            )
            target_report = target.report_material()
            target_reports.append(target_report)
            counts["input_rows"] += target_report["expected_trade_dates"]
            counts["indicator_value_rows"] += target_report["expected_trade_dates"] * len(EMA_PERIODS)
            counts["warming_up_rows"] += target_report["warming_up_rows"]
            counts["data_unavailable_rows"] += target_report["data_unavailable_rows"]
            counts["available_rows"] += target_report["available_rows"]
            counts["rebuild_targets"] += target_report["action"] == "rebuild"
        counts["targets"] = len(target_reports)
        return _plan_report_material(request=request, target_reports=target_reports, counts=counts)

    def apply_request(
        self,
        request: EmaHistoricalBackfillRequest,
        *,
        plan_report_hash: str,
        resume: bool = False,
    ) -> EmaHistoricalBackfillApplication:
        """Apply an unbounded historical request without retaining all rows.

        Each instrument is selected, calculated and committed independently.
        This is both the transaction/recovery boundary and the memory boundary;
        a later ``--resume`` therefore reuses completed immutable runs.
        """
        del resume
        dates = tuple(_trading_dates(request.start, request.end, self.is_trading_day))
        if not dates:
            raise ValueError("EMA backfill range has no KRX trading dates")
        instrument_ids = request.instrument_ids or self._discover_instrument_ids(request)
        outcomes: list[dict[str, Any]] = []
        created = 0
        reused = 0
        chunks = 0
        for instrument_chunk in _instrument_chunks(instrument_ids, request.chunk_size):
            chunks += 1
            for instrument_id in instrument_chunk:
                try:
                    outcome = EmaCalculationService(self.session).calculate(
                        instrument_id=instrument_id,
                        trade_dates=dates,
                        policy=request.policy,
                    )
                    self.session.commit()
                except Exception:
                    self.session.rollback()
                    raise
                outcomes.append(self._outcome_report(instrument_id, outcome))
                if outcome.reused:
                    reused += 1
                else:
                    created += 1
        return EmaHistoricalBackfillApplication(
            report_hash=plan_report_hash,
            attempted=len(instrument_ids),
            created=created,
            reused=reused,
            chunks=chunks,
            outcomes=tuple(outcomes),
        )

    def apply(
        self,
        plan: EmaHistoricalBackfillPlan,
        *,
        resume: bool = False,
    ) -> EmaHistoricalBackfillApplication:
        """Apply the plan in bounded commits.

        ``resume`` deliberately re-enters the same immutable calculation path.
        A completed target with the same input hash returns ``reused`` and does
        not append input/value rows or change that completed run.  A changed
        historical input correctly creates a separate rebuild generation.
        """
        del resume  # The idempotent calculation service is the resume mechanism.
        plan_report = plan.report()
        outcomes: list[dict[str, Any]] = []
        created = 0
        reused = 0
        chunks = 0
        for target_chunk in _chunks(plan.targets, plan.request.chunk_size):
            chunks += 1
            for target in target_chunk:
                try:
                    outcome = EmaCalculationService(self.session).calculate(
                        instrument_id=target.instrument_id,
                        trade_dates=target.trade_dates,
                        policy=plan.request.policy,
                    )
                    self.session.commit()
                except Exception:
                    self.session.rollback()
                    raise
                outcome_report = self._outcome_report(target.instrument_id, outcome)
                outcomes.append(outcome_report)
                if outcome.reused:
                    reused += 1
                else:
                    created += 1
        return EmaHistoricalBackfillApplication(
            report_hash=plan_report["report_hash"],
            attempted=len(plan.targets),
            created=created,
            reused=reused,
            chunks=chunks,
            outcomes=tuple(outcomes),
        )

    def _discover_instrument_ids(self, request: EmaHistoricalBackfillRequest) -> tuple[int, ...]:
        """Find mapped historical instruments without scanning every observation.

        ``ProviderSymbol`` is the compact historical identity catalogue.  The
        per-instrument selector still requires its immutable observation
        snapshot and records an unavailable value if source evidence is absent;
        discovery itself must not build a multi-million-row ``DISTINCT`` hash
        merely to find a few thousand candidate instrument IDs.
        """
        statement = (
            select(ProviderSymbol.instrument_id)
            .where(
                ProviderSymbol.provider == request.policy.provider,
                ProviderSymbol.mapping_status == "matched",
            )
            .distinct()
            .order_by(ProviderSymbol.instrument_id)
        )
        return tuple(value for value in self.session.scalars(statement) if value is not None)

    def _plan_target(
        self,
        *,
        instrument_id: int,
        trade_dates: tuple[date, ...],
        request: EmaHistoricalBackfillRequest,
    ) -> EmaHistoricalBackfillTarget:
        rows = self.selector.select_rows(
            instrument_id=instrument_id,
            trade_dates=trade_dates,
            policy=request.policy,
        )
        result = compute_ema(rows)
        action = self._action_for(instrument_id=instrument_id, rows=rows, policy=request.policy)
        return EmaHistoricalBackfillTarget(
            instrument_id=instrument_id,
            trade_dates=trade_dates,
            rows=rows,
            result=result,
            action=action,
        )

    def _action_for(
        self,
        *,
        instrument_id: int,
        rows: tuple[EmaInputRow, ...],
        policy: EmaSourcePolicy,
    ) -> str:
        series = self.repository.find_series(instrument_id=instrument_id, policy=policy)
        if series is None:
            return "backfill"
        current = self.repository.current_generation(series.id)
        if current is None:
            return "backfill"
        previous = self.repository.completed_input_rows(generation_id=current.id, policy=policy)
        comparison = compare_input_histories(previous, rows)
        if comparison.kind is InputHistoryKind.UNCHANGED:
            return "reused"
        if comparison.kind is InputHistoryKind.PREFIX_EXTENDED:
            return "incremental"
        return "rebuild"

    def _outcome_report(self, instrument_id: int, outcome: EmaCalculationOutcome) -> dict[str, Any]:
        input_hash = None
        result_hash = None
        if outcome.run_id is not None:
            from app.models.indicator import IndicatorCalculationRun

            run = self.session.get(IndicatorCalculationRun, outcome.run_id)
            if run is not None:
                input_hash = run.input_hash
                result_hash = run.result_hash
        return {
            "instrument_id": instrument_id,
            "series_id": outcome.series_id,
            "generation_id": outcome.generation_id,
            "run_id": outcome.run_id,
            "run_kind": outcome.run_kind,
            "reused": outcome.reused,
            "input_hash": input_hash,
            "result_hash": result_hash,
        }


def _trading_dates(start: date, end: date, is_trading_day: Callable[[date], bool]) -> Iterator[date]:
    current = start
    while current <= end:
        if is_trading_day(current):
            yield current
        current += timedelta(days=1)


def _chunks(values: tuple[EmaHistoricalBackfillTarget, ...], size: int) -> Iterator[tuple[EmaHistoricalBackfillTarget, ...]]:
    for offset in range(0, len(values), size):
        yield values[offset: offset + size]


def _instrument_chunks(values: tuple[int, ...], size: int) -> Iterator[tuple[int, ...]]:
    for offset in range(0, len(values), size):
        yield values[offset: offset + size]


def _plan_report_material(
    *,
    request: EmaHistoricalBackfillRequest,
    target_reports: list[dict[str, Any]],
    counts: Counter,
) -> dict[str, Any]:
    """Render the stable report payload shared by bounded and streaming plans."""
    input_rows = counts["input_rows"]
    value_rows = counts["indicator_value_rows"]
    storage_bytes = input_rows * _ESTIMATED_INPUT_SNAPSHOT_BYTES + value_rows * _ESTIMATED_VALUE_BYTES
    report_without_hash = {
        "schema_version": 1,
        "mode": "dry_run_plan",
        "request": request.report_material(),
        "counts": {
            "targets": counts["targets"],
            "input_rows": input_rows,
            "indicator_value_rows": value_rows,
            "warming_up_rows": counts["warming_up_rows"],
            "data_unavailable_rows": counts["data_unavailable_rows"],
            "available_rows": counts["available_rows"],
            "rebuild_targets": counts["rebuild_targets"],
        },
        "estimate": {
            "input_snapshot_rows": input_rows,
            "indicator_value_rows": value_rows,
            "storage_bytes": storage_bytes,
            "estimated_seconds": ceil(value_rows / _ESTIMATED_VALUES_PER_SECOND),
        },
        "targets": target_reports,
    }
    from hashlib import sha256

    return {
        **report_without_hash,
        "report_hash": sha256(canonical_json(report_without_hash).encode("utf-8")).hexdigest(),
    }


def _json_ready(value: Any) -> dict[str, Any]:
    """Use the input contract's canonical date/time representation in reports."""
    return json.loads(canonical_json(value))
