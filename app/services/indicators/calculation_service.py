"""Transactional EMA generation calculation and promotion.

The service works from copied source evidence and exposes a generation only
after each selected date has an input snapshot and exactly four EMA values.
It intentionally has no batch, API, or backfill-command concerns.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.indicator import IndicatorCalculationRun, IndicatorGeneration, IndicatorSeries
from app.repositories.indicator_repository import IndicatorRepository
from app.services.indicators.contracts import (
    EmaInputRow,
    EmaSourcePolicy,
    InputHistoryKind,
    compare_input_histories,
)
from app.services.indicators.ema import compute_ema
from app.services.indicators.input_selector import EmaInputSelector


@dataclass(frozen=True)
class EmaCalculationOutcome:
    series_id: int
    generation_id: int
    run_id: int | None
    run_kind: str | None
    reused: bool


@dataclass(frozen=True)
class EmaCleanupCandidate:
    generation_id: int
    series_id: int
    generation: int
    superseded_at: datetime


class EmaCalculationService:
    """Version transition coordinator for one instrument and frozen policy."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = IndicatorRepository(session)
        self.selector = EmaInputSelector(session)

    def calculate(
        self,
        *,
        instrument_id: int,
        trade_dates: Iterable[date],
        policy: EmaSourcePolicy,
    ) -> EmaCalculationOutcome:
        """Select, compare, persist, and atomically promote as required.

        This joins the surrounding session transaction.  Callers must commit
        that transaction after a successful return; an exception rolls the
        local savepoint back without exposing a partially completed run.
        """
        dates = tuple(sorted(set(trade_dates)))
        if not dates:
            raise ValueError("EMA calculation requires at least one expected trade date")
        with self.session.begin_nested():
            series = self.repository.find_series(instrument_id=instrument_id, policy=policy)
            if series is None:
                series = self.repository.create_series(instrument_id=instrument_id, policy=policy)
            series = self.repository.lock_series(series.id)
            current = self.repository.current_generation(series.id, lock=True)
            selected = self.selector.select_rows(
                instrument_id=instrument_id, trade_dates=dates, policy=policy,
            )
            if current is None:
                return self._start_full_generation(
                    series=series, parent=None, rows=selected, policy=policy, run_kind="backfill",
                    replacement_reason="initial_backfill",
                )

            previous = self.repository.completed_input_rows(generation_id=current.id, policy=policy)
            comparison = compare_input_histories(previous, selected)
            if comparison.kind is InputHistoryKind.UNCHANGED:
                last_run = self.session.scalar(
                    select(IndicatorCalculationRun)
                    .where(
                        IndicatorCalculationRun.generation_id == current.id,
                        IndicatorCalculationRun.status == "completed",
                    )
                    .order_by(IndicatorCalculationRun.completed_at.desc(), IndicatorCalculationRun.id.desc())
                    .limit(1)
                )
                return EmaCalculationOutcome(
                    series_id=series.id, generation_id=current.id,
                    run_id=last_run.id if last_run is not None else None,
                    run_kind=None, reused=True,
                )
            if comparison.kind is InputHistoryKind.PREFIX_EXTENDED:
                return self._append_incremental(
                    series=series, generation=current, previous=previous, rows=selected,
                )
            return self._start_full_generation(
                series=series, parent=current, rows=selected, policy=policy, run_kind="rebuild",
                replacement_reason="input_history_revised",
            )

    def _append_incremental(
        self,
        *,
        series: IndicatorSeries,
        generation: IndicatorGeneration,
        previous: tuple[EmaInputRow, ...],
        rows: tuple[EmaInputRow, ...],
    ) -> EmaCalculationOutcome:
        new_rows = rows[len(previous):]
        result = compute_ema(rows)
        new_dates = {row.trade_date for row in new_rows}
        new_values = tuple(value for value in result.values if value.trade_date in new_dates)
        run = self.repository.create_run(
            generation=generation, run_kind="incremental", input_cutoff=series.observation_cutoff,
            range_start=new_rows[0].trade_date, range_end=new_rows[-1].trade_date,
        )
        incremental_result = type(result)(
            values=new_values,
            row_fingerprints=result.row_fingerprints[len(previous):],
            prefix_hashes=result.prefix_hashes[len(previous):],
            input_hash=result.input_hash,
            result_hash=_result_hash_for_run(new_values),
        )
        self.repository.complete_run(run=run, input_rows=new_rows, result=incremental_result)
        return EmaCalculationOutcome(series.id, generation.id, run.id, "incremental", False)

    def _start_full_generation(
        self,
        *,
        series: IndicatorSeries,
        parent: IndicatorGeneration | None,
        rows: tuple[EmaInputRow, ...],
        policy: EmaSourcePolicy,
        run_kind: str,
        replacement_reason: str,
    ) -> EmaCalculationOutcome:
        generation = self.repository.create_generation(
            series_id=series.id,
            generation=self.repository.next_generation_number(series.id),
            parent_generation_id=parent.id if parent is not None else None,
            replacement_reason=replacement_reason,
            status="building",
        )
        result = compute_ema(rows)
        run = self.repository.create_run(
            generation=generation, run_kind=run_kind, input_cutoff=policy.observation_cutoff,
            range_start=rows[0].trade_date, range_end=rows[-1].trade_date,
        )
        self.repository.complete_run(run=run, input_rows=rows, result=result)
        now = datetime.now(UTC)
        if parent is not None:
            parent.status = "superseded"
            parent.superseded_at = now
            # The partial one-current index applies statement by statement.
            # Make the old row non-current before promoting its replacement.
            self.session.flush()
        generation.status = "current"
        self.session.flush()
        return EmaCalculationOutcome(series.id, generation.id, run.id, run_kind, False)

    def fail_run(self, run_id: int, *, failure_reason: str) -> None:
        """Record failure without making a building generation queryable."""
        with self.session.begin_nested():
            run = self.session.get(IndicatorCalculationRun, run_id)
            if run is None:
                raise KeyError(f"indicator calculation run not found: {run_id}")
            self.repository.fail_run(run, failure_reason=failure_reason)
            generation = self.session.get(IndicatorGeneration, run.generation_id)
            if generation is not None and generation.status == "building":
                generation.status = "failed"
                generation.failed_at = datetime.now(UTC)
                self.session.flush()

    def cleanup_candidates(
        self,
        *,
        now: datetime | None = None,
        referenced_generation_ids: Iterable[int] = (),
    ) -> tuple[EmaCleanupCandidate, ...]:
        """List, never delete, unreferenced generations past the 30-day hold."""
        cutoff = (now or datetime.now(UTC)) - timedelta(days=30)
        referenced = set(referenced_generation_ids)
        rows = self.session.scalars(select(IndicatorGeneration).where(
            IndicatorGeneration.status == "superseded",
            IndicatorGeneration.superseded_at.is_not(None),
            IndicatorGeneration.superseded_at <= cutoff,
        ).order_by(IndicatorGeneration.superseded_at, IndicatorGeneration.id))
        return tuple(
            EmaCleanupCandidate(
                generation_id=row.id, series_id=row.series_id, generation=row.generation,
                superseded_at=row.superseded_at,
            )
            for row in rows if row.id not in referenced
        )


def _result_hash_for_run(values: tuple) -> str:
    # The full-generation result hash remains on the immutable input lineage.
    # Each incremental run records a hash of exactly the values it owns.
    from app.services.indicators.contracts import result_hash

    return result_hash(values)
