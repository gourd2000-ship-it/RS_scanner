"""Repository boundary for append-only EMA calculation persistence."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.indicator import (
    IndicatorCalculationRun,
    IndicatorGeneration,
    IndicatorInputSnapshot,
    IndicatorSeries,
    IndicatorValue,
    PriceObservationIdentitySnapshot,
)
from app.models.instrument import Instrument
from app.models.symbol import Symbol
from app.services.indicators.contracts import (
    EMA_FORMULA_VERSION,
    EmaCalculationResult,
    EmaInputRow,
    EmaSourcePolicy,
    EmaValue,
    IdentitySnapshot,
    InputReasonCode,
    ValidationCaseEvidence,
    input_row_fingerprint,
)


@dataclass(frozen=True)
class CurrentEmaMetadata:
    """Freshness metadata for an exposed current EMA generation."""

    series_id: int
    generation_id: int
    as_of: date
    calculated_at: datetime


@dataclass(frozen=True)
class EmaStoredValue:
    """One persisted period value returned from the current generation."""

    trade_date: date
    period: int
    value: Decimal | None
    status: str
    reason_code: str | None
    available_observations: int


class IndicatorRepository:
    """Persistence boundary for immutable EMA evidence and calculation output.

    Promotion of a generation and completion transactions belong to the
    calculation orchestration layer.  This repository deliberately provides no
    update or delete operation for completed runs or their child rows.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def find_instruments_for_code(self, *, code: str) -> tuple[Instrument, ...]:
        """Return every historical identity known for a displayed code.

        The legacy Symbol table can retain a prior code and the canonical
        Instrument also has a KRX short code.  Treating either one as a unique
        identity would make a code reuse silently select the wrong EMA series.
        """
        rows = self.session.scalars(
            select(Instrument)
            .outerjoin(Symbol, Symbol.instrument_id == Instrument.id)
            .where(
                or_(
                    Instrument.krx_short_code == code,
                    Symbol.code == code,
                    Symbol.legacy_code == code,
                )
            )
            .order_by(Instrument.id)
        ).unique()
        return tuple(rows)

    def get_instrument(self, instrument_id: int) -> Instrument | None:
        return self.session.get(Instrument, instrument_id)

    def current_ema_metadata(self, *, instrument_id: int) -> CurrentEmaMetadata | None:
        """Return freshness only from a fully completed current generation."""
        # An instrument can have several current series when the immutable
        # source-policy tuple changes.  Publish one complete series rather
        # than letting a code lookup combine policy versions.  Completion time
        # is the primary freshness rule; generation then series ID make an
        # equal-time result deterministic.
        row = self.session.execute(
            select(
                IndicatorSeries.id,
                IndicatorGeneration.id,
                func.max(IndicatorValue.trade_date),
                func.max(IndicatorCalculationRun.completed_at),
            )
            .select_from(IndicatorValue)
            .join(
                IndicatorCalculationRun,
                (IndicatorCalculationRun.id == IndicatorValue.calculation_run_id)
                & (IndicatorCalculationRun.generation_id == IndicatorValue.generation_id),
            )
            .join(IndicatorGeneration, IndicatorGeneration.id == IndicatorValue.generation_id)
            .join(IndicatorSeries, IndicatorSeries.id == IndicatorGeneration.series_id)
            .where(
                IndicatorSeries.instrument_id == instrument_id,
                IndicatorGeneration.status == "current",
                IndicatorCalculationRun.status == "completed",
            )
            .group_by(IndicatorSeries.id, IndicatorGeneration.id)
            .order_by(
                func.max(IndicatorCalculationRun.completed_at).desc(),
                IndicatorGeneration.id.desc(),
                IndicatorSeries.id.desc(),
            )
            .limit(1)
        ).first()
        if row is None or row[2] is None or row[3] is None:
            return None
        return CurrentEmaMetadata(
            series_id=row[0],
            generation_id=row[1],
            as_of=row[2],
            calculated_at=_as_utc(row[3]),
        )

    def current_ema_page(
        self,
        *,
        instrument_id: int,
        series_id: int,
        generation_id: int,
        start: date,
        end: date,
        page: int,
        size: int,
    ) -> tuple[tuple[EmaStoredValue, ...], int]:
        """Read an ordered page by trading day from one current generation."""
        filters = (
            IndicatorSeries.instrument_id == instrument_id,
            IndicatorSeries.id == series_id,
            IndicatorGeneration.id == generation_id,
            IndicatorGeneration.status == "current",
            IndicatorCalculationRun.status == "completed",
            IndicatorValue.trade_date >= start,
            IndicatorValue.trade_date <= end,
        )
        date_statement = (
            select(IndicatorValue.trade_date)
            .select_from(IndicatorValue)
            .join(
                IndicatorCalculationRun,
                (IndicatorCalculationRun.id == IndicatorValue.calculation_run_id)
                & (IndicatorCalculationRun.generation_id == IndicatorValue.generation_id),
            )
            .join(IndicatorGeneration, IndicatorGeneration.id == IndicatorValue.generation_id)
            .join(IndicatorSeries, IndicatorSeries.id == IndicatorGeneration.series_id)
            .where(*filters)
            .distinct()
            .order_by(IndicatorValue.trade_date)
        )
        total_count = self.session.scalar(select(func.count()).select_from(date_statement.subquery())) or 0
        trade_dates = tuple(
            self.session.scalars(date_statement.offset((page - 1) * size).limit(size))
        )
        if not trade_dates:
            return (), total_count
        rows = self.session.execute(
            select(
                IndicatorValue.trade_date,
                IndicatorValue.period,
                IndicatorValue.value,
                IndicatorValue.status,
                IndicatorValue.reason_code,
                IndicatorValue.available_observations,
            )
            .select_from(IndicatorValue)
            .join(
                IndicatorCalculationRun,
                (IndicatorCalculationRun.id == IndicatorValue.calculation_run_id)
                & (IndicatorCalculationRun.generation_id == IndicatorValue.generation_id),
            )
            .join(IndicatorGeneration, IndicatorGeneration.id == IndicatorValue.generation_id)
            .join(IndicatorSeries, IndicatorSeries.id == IndicatorGeneration.series_id)
            .where(*filters, IndicatorValue.trade_date.in_(trade_dates))
            .order_by(IndicatorValue.trade_date, IndicatorValue.period)
        )
        return (
            tuple(
                EmaStoredValue(
                    trade_date=row[0], period=row[1], value=row[2], status=row[3],
                    reason_code=row[4], available_observations=row[5],
                )
                for row in rows
            ),
            total_count,
        )

    def create_identity_snapshot(
        self,
        *,
        price_observation_id: int,
        instrument_id: int | None,
        provider_symbol_mapping_id: int | None,
        provider: str,
        provider_symbol: str | None,
        mapping_status: str | None,
        mapping_valid_from: date | None,
        mapping_valid_to: date | None,
        resolver_version: str | None,
        resolved_at: datetime | None,
    ) -> PriceObservationIdentitySnapshot:
        """Persist evidence supplied by a resolver; never infer it from Symbol."""
        snapshot = PriceObservationIdentitySnapshot(
            price_observation_id=price_observation_id,
            instrument_id=instrument_id,
            provider_symbol_mapping_id=provider_symbol_mapping_id,
            provider=provider,
            provider_symbol=provider_symbol,
            mapping_status=mapping_status,
            mapping_valid_from=mapping_valid_from,
            mapping_valid_to=mapping_valid_to,
            resolver_version=resolver_version,
            resolved_at=resolved_at,
        )
        self.session.add(snapshot)
        self.session.flush()
        return snapshot

    def create_series(self, *, instrument_id: int, policy: EmaSourcePolicy) -> IndicatorSeries:
        series = IndicatorSeries(
            instrument_id=instrument_id,
            input_policy_version=policy.version,
            formula_version=EMA_FORMULA_VERSION,
            source_provider=policy.provider,
            adjustment_policy=policy.adjustment_type,
            allowed_parser_versions=sorted(policy.allowed_parser_versions),
            observation_cutoff=policy.observation_cutoff,
        )
        self.session.add(series)
        self.session.flush()
        return series

    def find_series(self, *, instrument_id: int, policy: EmaSourcePolicy) -> IndicatorSeries | None:
        """Find the exact frozen policy series without treating policy drift as equal."""
        candidates = self.session.scalars(select(IndicatorSeries).where(
            IndicatorSeries.instrument_id == instrument_id,
            IndicatorSeries.input_policy_version == policy.version,
            IndicatorSeries.formula_version == EMA_FORMULA_VERSION,
            IndicatorSeries.source_provider == policy.provider,
            IndicatorSeries.adjustment_policy == policy.adjustment_type,
            IndicatorSeries.observation_cutoff == policy.observation_cutoff,
        ))
        expected_versions = tuple(sorted(policy.allowed_parser_versions))
        return next((row for row in candidates if tuple(sorted(row.allowed_parser_versions)) == expected_versions), None)

    def get_or_create_series(self, *, instrument_id: int, policy: EmaSourcePolicy) -> IndicatorSeries:
        """Create a policy series once, including under concurrent first use.

        The policy uniqueness constraint is the durable arbiter.  A competing
        insert is isolated in a savepoint, then the winning committed row is
        fetched instead of leaving the outer calculation transaction failed.
        """
        existing = self.find_series(instrument_id=instrument_id, policy=policy)
        if existing is not None:
            return existing
        try:
            with self.session.begin_nested():
                return self.create_series(instrument_id=instrument_id, policy=policy)
        except IntegrityError:
            existing = self.find_series(instrument_id=instrument_id, policy=policy)
            if existing is None:
                raise
            return existing

    def lock_series(self, series_id: int) -> IndicatorSeries:
        """Serialize selection and generation promotion for one policy series."""
        series = self.session.scalar(
            select(IndicatorSeries).where(IndicatorSeries.id == series_id).with_for_update()
        )
        if series is None:
            raise KeyError(f"indicator series not found: {series_id}")
        return series

    def current_generation(self, series_id: int, *, lock: bool = False) -> IndicatorGeneration | None:
        statement = select(IndicatorGeneration).where(
            IndicatorGeneration.series_id == series_id,
            IndicatorGeneration.status == "current",
        )
        if lock:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def next_generation_number(self, series_id: int) -> int:
        maximum = self.session.scalar(select(func.max(IndicatorGeneration.generation)).where(
            IndicatorGeneration.series_id == series_id
        ))
        return int(maximum or 0) + 1

    def create_generation(
        self,
        *,
        series_id: int,
        generation: int,
        parent_generation_id: int | None = None,
        replacement_reason: str | None = None,
        status: str = "building",
    ) -> IndicatorGeneration:
        row = IndicatorGeneration(
            series_id=series_id,
            generation=generation,
            parent_generation_id=parent_generation_id,
            replacement_reason=replacement_reason,
            status=status,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def create_run(
        self,
        *,
        generation: IndicatorGeneration,
        run_kind: str,
        input_cutoff: datetime,
        range_start: date | None = None,
        range_end: date | None = None,
    ) -> IndicatorCalculationRun:
        """Start one run; the partial unique index serializes a series.

        Incremental output extends the one logical generation currently
        exposed by a series.  A rebuild/backfill starts from a building
        generation and may later be promoted by the orchestration service.
        """
        if generation.status not in {"building", "current"}:
            raise ValueError("a calculation run requires a building or current generation")
        if run_kind == "incremental" and generation.status != "current":
            raise ValueError("an incremental calculation run requires the current generation")
        row = IndicatorCalculationRun(
            generation_id=generation.id,
            series_id=generation.series_id,
            run_kind=run_kind,
            status="running",
            input_cutoff=input_cutoff,
            range_start=range_start,
            range_end=range_end,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def append_inputs(
        self,
        *,
        run: IndicatorCalculationRun,
        rows: Sequence[EmaInputRow],
        prefix_hashes: Sequence[str],
    ) -> list[IndicatorInputSnapshot]:
        """Copy contract rows so later source edits cannot change this run."""
        self.assert_run_running(run)
        if len(rows) != len(prefix_hashes):
            raise ValueError("EMA input rows and prefix hashes must have equal length")
        snapshots = [self._input_snapshot(run, row, prefix_hash) for row, prefix_hash in zip(rows, prefix_hashes, strict=True)]
        self.session.add_all(snapshots)
        self.session.flush()
        return snapshots

    def append_values(
        self, *, run: IndicatorCalculationRun, values: Iterable[EmaValue]
    ) -> list[IndicatorValue]:
        self.assert_run_running(run)
        rows = [
            IndicatorValue(
                calculation_run_id=run.id,
                generation_id=run.generation_id,
                period=value.period,
                trade_date=value.trade_date,
                value=value.value,
                status=value.status.value,
                reason_code=value.reason_code.value if value.reason_code is not None else None,
                available_observations=value.available_observations,
                input_prefix_hash=value.input_prefix_hash,
            )
            for value in values
        ]
        self.session.add_all(rows)
        self.session.flush()
        return rows

    def append_result(
        self,
        *,
        run: IndicatorCalculationRun,
        input_rows: Sequence[EmaInputRow],
        result: EmaCalculationResult,
    ) -> tuple[list[IndicatorInputSnapshot], list[IndicatorValue]]:
        """Persist calculator input/output while the run is still mutable."""
        inputs = self.append_inputs(run=run, rows=input_rows, prefix_hashes=result.prefix_hashes)
        values = self.append_values(run=run, values=result.values)
        return inputs, values

    def complete_run(
        self,
        *,
        run: IndicatorCalculationRun,
        input_rows: Sequence[EmaInputRow],
        result: EmaCalculationResult,
        completed_at: datetime | None = None,
    ) -> IndicatorCalculationRun:
        """Atomically mark a fully materialized run complete.

        The caller must keep this method in its transaction.  We flush child
        snapshots and all four period values before the status transition so
        PostgreSQL's completed-run trigger observes a complete artifact.
        """
        self.assert_run_running(run)
        if len(result.values) != len(input_rows) * 4:
            raise ValueError("every EMA input date must have all four period values")
        expected_dates = {row.trade_date for row in input_rows}
        if len(expected_dates) != len(input_rows):
            raise ValueError("EMA run input dates must be unique")
        by_date: dict[date, set[int]] = {}
        for value in result.values:
            by_date.setdefault(value.trade_date, set()).add(value.period)
        if set(by_date) != expected_dates or any(len(periods) != 4 for periods in by_date.values()):
            raise ValueError("every EMA input date must have exactly four periods")
        inputs, values = self.append_result(run=run, input_rows=input_rows, result=result)
        run.input_hash = result.input_hash
        run.result_hash = result.result_hash
        run.input_count = len(inputs)
        run.result_count = len(values)
        run.excluded_count = sum(row.effective_reason() is not None for row in input_rows)
        run.completed_at = completed_at or datetime.now(UTC)
        run.status = "completed"
        self.session.flush()
        return run

    def fail_run(self, run: IndicatorCalculationRun, *, failure_reason: str) -> IndicatorCalculationRun:
        self.assert_run_running(run)
        run.status = "failed"
        run.failed_at = datetime.now(UTC)
        run.failure_reason = failure_reason[:200]
        self.session.flush()
        return run

    def completed_input_rows(
        self, *, generation_id: int, policy: EmaSourcePolicy
    ) -> tuple[EmaInputRow, ...]:
        """Rehydrate only copied evidence; source tables are never revisited."""
        rows = self.session.scalars(
            select(IndicatorInputSnapshot)
            .join(IndicatorCalculationRun, IndicatorCalculationRun.id == IndicatorInputSnapshot.calculation_run_id)
            .where(
                IndicatorInputSnapshot.generation_id == generation_id,
                IndicatorCalculationRun.status == "completed",
            )
            .order_by(IndicatorInputSnapshot.trade_date, IndicatorInputSnapshot.id)
        )
        materialized: list[EmaInputRow] = []
        seen_dates: set[date] = set()
        for row in rows:
            if row.trade_date in seen_dates:
                raise ValueError("completed generation contains duplicate input snapshots")
            seen_dates.add(row.trade_date)
            identity = None
            if row.price_observation_identity_snapshot_id is not None:
                identity = IdentitySnapshot(
                    snapshot_id=row.price_observation_identity_snapshot_id,
                    instrument_id=row.instrument_id,
                    provider=row.provider,
                    provider_symbol=row.provider_symbol,
                    provider_mapping_id=row.provider_symbol_mapping_id,
                    mapping_status=row.mapping_status,
                    valid_from=row.mapping_valid_from,
                    valid_to=row.mapping_valid_to,
                    resolver_version=row.resolver_version,
                    resolved_at=_as_utc(row.resolved_at),
                )
            materialized.append(EmaInputRow(
                trade_date=row.trade_date, instrument_id=row.instrument_id,
                symbol_id=row.source_symbol_id, observation_id=row.price_observation_id,
                identity=identity, provider=row.provider, provider_symbol=row.provider_symbol,
                adjustment_type=row.adjustment_type, parser_version=row.parser_version,
                close=row.close, volume=row.volume, observed_at=_as_utc(row.observed_at),
                payload_hash=row.payload_hash, correction_ids=tuple(row.correction_ids),
                validation_cases=tuple(
                    ValidationCaseEvidence(
                        case_id=item["case_id"], case_status=item["case_status"], decision=item.get("decision")
                    ) for item in row.validation_evidence
                ),
                input_status=row.input_status,
                reason_code=InputReasonCode(row.reason_code) if row.reason_code is not None else None,
                source_policy=policy,
            ))
        return tuple(materialized)

    def assert_run_running(self, run: IndicatorCalculationRun) -> None:
        """Lock the persisted run and allow writes only during ``running``.

        The row lock prevents another calculation worker from failing or
        completing the run between the state check and its child inserts.
        """
        status = self.session.scalar(
            select(IndicatorCalculationRun.status)
            .where(IndicatorCalculationRun.id == run.id)
            .with_for_update()
        )
        if status is None:
            raise KeyError(f"indicator calculation run not found: {run.id}")
        if status == "completed":
            raise ValueError("completed indicator calculation runs are immutable")
        if status != "running":
            raise ValueError(f"only running indicator calculation runs are writable (status={status})")

    @staticmethod
    def _input_snapshot(
        run: IndicatorCalculationRun, row: EmaInputRow, prefix_hash: str
    ) -> IndicatorInputSnapshot:
        identity = row.identity
        return IndicatorInputSnapshot(
            calculation_run_id=run.id,
            generation_id=run.generation_id,
            trade_date=row.trade_date,
            instrument_id=row.instrument_id,
            source_symbol_id=row.symbol_id,
            price_observation_id=row.observation_id,
            price_observation_identity_snapshot_id=identity.snapshot_id if identity is not None else None,
            provider_symbol_mapping_id=identity.provider_mapping_id if identity is not None else None,
            provider=row.provider,
            provider_symbol=row.provider_symbol,
            adjustment_type=row.adjustment_type,
            parser_version=row.parser_version,
            close=row.close,
            volume=row.volume,
            observed_at=row.observed_at,
            payload_hash=row.payload_hash,
            mapping_status=identity.mapping_status if identity is not None else None,
            mapping_valid_from=identity.valid_from if identity is not None else None,
            mapping_valid_to=identity.valid_to if identity is not None else None,
            resolver_version=identity.resolver_version if identity is not None else None,
            resolved_at=identity.resolved_at if identity is not None else None,
            correction_ids=list(row.correction_ids),
            validation_evidence=[case.fingerprint_material() for case in row.validation_cases],
            input_status=row.input_status.value,
            reason_code=row.reason_code.value if row.reason_code is not None else None,
            row_hash=input_row_fingerprint(row),
            prefix_hash=prefix_hash,
        )


def _as_utc(value: datetime | None) -> datetime | None:
    """Source tables historically persisted UTC values without tz metadata."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
