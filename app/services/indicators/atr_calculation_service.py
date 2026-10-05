"""Transactional ATR14 generations using shared selection evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.indicator import IndicatorCalculationRun
from app.repositories.atr_indicator_repository import AtrIndicatorRepository
from app.services.indicators.contracts import EmaSourcePolicy, canonical_json, prefix_hash
from app.services.indicators.input_selector import EmaInputSelector
from app.services.indicators.atr import AtrInput, AtrResult, compute_atr14


@dataclass(frozen=True)
class AtrCalculationOutcome:
    series_id: int
    generation_id: int
    run_id: int
    run_kind: str | None
    reused: bool


class AtrCalculationError(RuntimeError):
    """A failed attempt remains inspectable in the caller's transaction."""

    def __init__(self, run_id: int) -> None:
        self.run_id = run_id
        super().__init__(f"ATR calculation failed (run_id={run_id})")


class AtrCalculationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = AtrIndicatorRepository(session)
        self.selector = EmaInputSelector(session)

    def calculate(
        self, *, instrument_id: int, trade_dates: Iterable[date], policy: EmaSourcePolicy,
    ) -> AtrCalculationOutcome:
        """Join the caller transaction; callers commit successful or failed attempts.

        A local savepoint removes partial output before marking an attempt failed.
        Failure never promotes a replacement or invalidates the previous current
        generation. The series lock and unique running-run index serialize workers.
        """
        dates = tuple(sorted(set(trade_dates)))
        if not dates:
            raise ValueError("ATR calculation requires at least one expected trade date")
        failure = None
        with self.session.begin_nested():
            series = self.repository.get_or_create_series(instrument_id=instrument_id, policy=policy)
            series = self.repository.lock_series(series.id)
            if self.session.scalar(select(IndicatorCalculationRun.id).where(
                IndicatorCalculationRun.series_id == series.id,
                IndicatorCalculationRun.status == "running",
            )) is not None:
                raise ValueError("indicator series already has a running calculation")
            current = self.repository.current_generation(series.id, lock=True)
            rows = self.selector.select_rows(instrument_id=instrument_id, trade_dates=dates, policy=policy)
            evidence = self.repository.get_or_create_evidence_rows(
                input_policy_id=series.input_policy_id, rows=rows,
            )
            previous = self.repository.completed_evidence(current.id) if current is not None else ()
            old_keys = tuple(row.evidence_key for row in previous)
            keys = tuple(row.evidence_key for row in evidence)
            if current is not None and old_keys == keys:
                last_run = self.session.scalar(select(IndicatorCalculationRun).where(
                    IndicatorCalculationRun.generation_id == current.id,
                    IndicatorCalculationRun.status == "completed",
                ).order_by(IndicatorCalculationRun.completed_at.desc(), IndicatorCalculationRun.id.desc()).limit(1))
                return AtrCalculationOutcome(series.id, current.id, last_run.id, None, True)
            incremental = current is not None and len(keys) > len(old_keys) and keys[:len(old_keys)] == old_keys
            run_kind = "incremental" if incremental else "rebuild" if current is not None else "backfill"
            generation = current if incremental else self.repository.create_generation(
                series_id=series.id, generation=self.repository.next_generation_number(series.id),
                parent_generation_id=current.id if current is not None else None,
                replacement_reason="input_history_revised" if current is not None else "initial_backfill",
            )
            offset = len(previous) if incremental else 0
            run = self.repository.create_run(
                generation=generation, run_kind=run_kind, input_cutoff=policy.observation_cutoff,
                range_start=rows[offset].trade_date, range_end=rows[-1].trade_date,
            )
            try:
                with self.session.begin_nested():
                    # Recalculate the full window so resets and Decimal values match
                    # the read-only calculator; only the new suffix is persisted.
                    inputs = tuple(AtrInput(
                        row.trade_date, row.high, row.low, row.close,
                        row.effective_reason().value if row.effective_reason() is not None else None,
                    ) for row in rows)
                    result = compute_atr14(inputs)
                    prefixes = []
                    previous_prefix = None
                    for key in keys:
                        previous_prefix = prefix_hash(previous_prefix, key)
                        prefixes.append(previous_prefix)
                    if incremental:
                        values = result.values[offset:]
                        result = AtrResult(values, sha256(canonical_json(
                            [value.material() for value in values]).encode("utf-8")).hexdigest())
                    self.repository.complete_atr_run(
                        run=run, evidence=evidence[offset:], prefix_hashes=prefixes[offset:], result=result,
                    )
                    if not incremental:
                        if current is not None:
                            current.status = "superseded"
                            current.superseded_at = datetime.now(UTC)
                            self.session.flush()
                        generation.status = "current"
                        self.session.flush()
            except Exception as exc:
                self.repository.fail_run(run, failure_reason=type(exc).__name__)
                if generation.status == "building":
                    generation.status = "failed"
                    generation.failed_at = datetime.now(UTC)
                    self.session.flush()
                failure = AtrCalculationError(run.id)
            outcome = AtrCalculationOutcome(series.id, generation.id, run.id, run_kind, False)
        if failure is not None:
            raise failure
        return outcome
