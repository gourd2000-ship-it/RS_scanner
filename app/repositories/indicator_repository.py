"""Repository boundary for append-only EMA calculation persistence."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.indicator import (
    IndicatorCalculationRun,
    IndicatorGeneration,
    IndicatorInputSnapshot,
    IndicatorSeries,
    IndicatorValue,
    PriceObservationIdentitySnapshot,
)
from app.services.indicators.contracts import (
    EMA_FORMULA_VERSION,
    EmaCalculationResult,
    EmaInputRow,
    EmaSourcePolicy,
    EmaValue,
    input_row_fingerprint,
)


class IndicatorRepository:
    """Write only immutable EMA evidence and calculation output.

    Promotion of a generation and completion transactions belong to the
    calculation orchestration layer.  This repository deliberately provides no
    update or delete operation for completed runs or their child rows.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

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
        self.assert_run_mutable(run)
        if len(rows) != len(prefix_hashes):
            raise ValueError("EMA input rows and prefix hashes must have equal length")
        snapshots = [self._input_snapshot(run, row, prefix_hash) for row, prefix_hash in zip(rows, prefix_hashes, strict=True)]
        self.session.add_all(snapshots)
        self.session.flush()
        return snapshots

    def append_values(
        self, *, run: IndicatorCalculationRun, values: Iterable[EmaValue]
    ) -> list[IndicatorValue]:
        self.assert_run_mutable(run)
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

    def assert_run_mutable(self, run: IndicatorCalculationRun) -> None:
        status = self.session.scalar(
            select(IndicatorCalculationRun.status).where(IndicatorCalculationRun.id == run.id)
        )
        if status is None:
            raise KeyError(f"indicator calculation run not found: {run.id}")
        if status == "completed":
            raise ValueError("completed indicator calculation runs are immutable")

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
