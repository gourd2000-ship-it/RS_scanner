"""Volume MA50 persistence over the shared immutable input tables."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.indicator import (
    IndicatorCalculationRun, IndicatorInputEvidence, IndicatorInputPolicy,
    IndicatorRunInput, IndicatorSeries, IndicatorValue,
)
from app.repositories.indicator_repository import IndicatorRepository, _as_utc
from app.services.indicators.contracts import EmaInputRow, EmaSourcePolicy
from app.services.indicators.volume_sma import VOLUME_SMA_PERIOD, VolumeSmaResult


COMMON_INPUT_POLICY_VERSION = "validated-observation-ohlcv-v1"
# These versions describe the EmaInputSelector rules reused by Volume MA50.
SELECTOR_VERSION = "ema-input-selector-close-v3"
VALIDATION_VERSION = "ema-input-validation-close-v3"
CORRECTION_VERSION = "ema-approved-close-correction-v1"


class VolumeIndicatorRepository(IndicatorRepository):
    """Reuse generation/run locking without changing the legacy EMA writer."""

    def get_or_create_policy(self, policy: EmaSourcePolicy) -> IndicatorInputPolicy:
        fields = dict(
            version=COMMON_INPUT_POLICY_VERSION, provider=policy.provider,
            adjustment_type=policy.adjustment_type,
            allowed_parser_versions=sorted(set(policy.allowed_parser_versions)),
            observation_cutoff=policy.observation_cutoff,
            selector_version=SELECTOR_VERSION, validation_version=VALIDATION_VERSION,
            correction_version=CORRECTION_VERSION,
        )

        def find():
            candidates = self.session.scalars(select(IndicatorInputPolicy).where(
                IndicatorInputPolicy.version == fields["version"],
                IndicatorInputPolicy.provider == policy.provider,
                IndicatorInputPolicy.adjustment_type == policy.adjustment_type,
                IndicatorInputPolicy.observation_cutoff == policy.observation_cutoff,
                IndicatorInputPolicy.selector_version == SELECTOR_VERSION,
                IndicatorInputPolicy.validation_version == VALIDATION_VERSION,
                IndicatorInputPolicy.correction_version == CORRECTION_VERSION,
            ))
            return next((row for row in candidates
                         if row.allowed_parser_versions == fields["allowed_parser_versions"]), None)

        existing = find()
        if existing is not None:
            return existing
        try:
            with self.session.begin_nested():
                row = IndicatorInputPolicy(**fields)
                self.session.add(row)
                self.session.flush()  # DB supplies the canonical fingerprint.
                return row
        except IntegrityError:
            existing = find()
            if existing is None:
                raise
            return existing

    def get_or_create_series(self, *, instrument_id: int, policy: EmaSourcePolicy) -> IndicatorSeries:
        common = self.get_or_create_policy(policy)

        def find():
            return self.session.scalar(select(IndicatorSeries).where(
                IndicatorSeries.instrument_id == instrument_id,
                IndicatorSeries.indicator_kind == "volume_sma",
                IndicatorSeries.input_policy_id == common.id,
            ))

        existing = find()
        if existing is not None:
            return existing
        try:
            with self.session.begin_nested():
                row = IndicatorSeries(
                    instrument_id=instrument_id, indicator_kind="volume_sma",
                    input_field="volume", periods="50", formula_version="volume-sma-v1",
                    input_policy_version=common.version, input_policy_id=common.id,
                    source_provider=common.provider, adjustment_policy=common.adjustment_type,
                    allowed_parser_versions=common.allowed_parser_versions,
                    observation_cutoff=common.observation_cutoff,
                )
                self.session.add(row)
                self.session.flush()
                return row
        except IntegrityError:
            existing = find()
            if existing is None:
                raise
            return existing

    def get_or_create_evidence(
        self, *, input_policy_id: int, row: EmaInputRow,
    ) -> IndicatorInputEvidence:
        return self.get_or_create_evidence_rows(input_policy_id=input_policy_id, rows=(row,))[0]

    def get_or_create_evidence_rows(
        self, *, input_policy_id: int, rows: Sequence[EmaInputRow],
    ) -> tuple[IndicatorInputEvidence, ...]:
        """Fetch a request range once and flush new facts in one savepoint.

        Only PostgreSQL generates durable evidence keys. The local comparison
        keeps nonfinite prices intact, so invalid inputs do not enter the legacy
        EMA fingerprint serializer. A competing insert rolls back the whole
        new batch; refetch its winners and retry only still-missing facts.
        """
        if not rows:
            return ()
        fields = tuple(_evidence_fields(input_policy_id, row) for row in rows)
        materials = tuple(_comparison_material(item) for item in fields)
        existing = self._find_evidence(input_policy_id=input_policy_id, rows=rows)
        missing = {material: item for material, item in zip(materials, fields, strict=True)
                   if material not in existing}
        while missing:
            try:
                with self.session.begin_nested():
                    new_rows = {material: IndicatorInputEvidence(**item) for material, item in missing.items()}
                    self.session.add_all(new_rows.values())
                    self.session.flush()  # Read each server-generated evidence key via RETURNING.
                existing.update(new_rows)
                break
            except IntegrityError:
                existing = self._find_evidence(input_policy_id=input_policy_id, rows=rows)
                remaining = {material: item for material, item in missing.items() if material not in existing}
                if len(remaining) == len(missing):
                    raise  # Not a recoverable duplicate-evidence conflict.
                missing = remaining
        return tuple(existing[material] for material in materials)

    def _find_evidence(
        self, *, input_policy_id: int, rows: Sequence[EmaInputRow],
    ) -> dict[tuple, IndicatorInputEvidence]:
        candidates = self.session.scalars(select(IndicatorInputEvidence).where(
            IndicatorInputEvidence.input_policy_id == input_policy_id,
            IndicatorInputEvidence.instrument_id.in_({row.instrument_id for row in rows}),
            IndicatorInputEvidence.trade_date >= min(row.trade_date for row in rows),
            IndicatorInputEvidence.trade_date <= max(row.trade_date for row in rows),
        ))
        return {_comparison_material({
            column.name: getattr(candidate, column.name)
            for column in IndicatorInputEvidence.__table__.columns
            if column.name not in {"id", "evidence_key", "created_at"}
        }): candidate for candidate in candidates}

    def completed_evidence(self, generation_id: int) -> tuple[IndicatorInputEvidence, ...]:
        rows = tuple(self.session.scalars(
            select(IndicatorInputEvidence)
            .join(IndicatorRunInput, IndicatorRunInput.evidence_id == IndicatorInputEvidence.id)
            .join(IndicatorCalculationRun, IndicatorCalculationRun.id == IndicatorRunInput.calculation_run_id)
            .where(IndicatorCalculationRun.generation_id == generation_id,
                   IndicatorCalculationRun.status == "completed")
            .order_by(IndicatorInputEvidence.trade_date)
        ))
        if len({row.trade_date for row in rows}) != len(rows):
            raise ValueError("completed generation contains duplicate input dates")
        return rows

    def complete_volume_run(
        self, *, run: IndicatorCalculationRun, evidence: Sequence[IndicatorInputEvidence],
        prefix_hashes: Sequence[str], result: VolumeSmaResult,
    ) -> None:
        self.assert_run_running(run)
        dates = tuple(row.trade_date for row in evidence)
        if (not dates or len(set(dates)) != len(dates) or len(evidence) != len(prefix_hashes)
                or tuple(value.trade_date for value in result.values) != dates):
            raise ValueError("every Volume input date must have exactly one matching value and prefix")
        series = self.session.get(IndicatorSeries, run.series_id)
        if series is None or series.indicator_kind != "volume_sma" or any(
            row.instrument_id != series.instrument_id or row.input_policy_id != series.input_policy_id
            for row in evidence
        ):
            raise ValueError("Volume run evidence must match its series instrument and policy")
        self.session.add_all([
            IndicatorRunInput(calculation_run_id=run.id, evidence_id=row.id,
                              ordinal=ordinal, prefix_hash=prefix)
            for ordinal, (row, prefix) in enumerate(zip(evidence, prefix_hashes, strict=True))
        ])
        self.session.add_all([
            IndicatorValue(
                calculation_run_id=run.id, generation_id=run.generation_id,
                indicator_kind="volume_sma", period=VOLUME_SMA_PERIOD, trade_date=value.trade_date,
                value=value.value, status=value.status.value, reason_code=value.reason_code,
                available_observations=value.available_observations, input_prefix_hash=prefix,
            ) for value, prefix in zip(result.values, prefix_hashes, strict=True)
        ])
        self.session.flush()
        run.input_hash = prefix_hashes[-1]
        run.result_hash = result.result_hash
        run.input_count = run.result_count = len(evidence)
        run.excluded_count = sum(value.status.value == "data_unavailable" for value in result.values)
        run.completed_at = datetime.now(UTC)
        run.status = "completed"
        self.session.flush()


def _evidence_fields(input_policy_id: int, row: EmaInputRow) -> dict[str, object]:
    """Copy selection facts directly; invalid prices are evidence, not hashes."""
    identity = row.identity
    return dict(
        input_policy_id=input_policy_id, trade_date=row.trade_date, instrument_id=row.instrument_id,
        source_symbol_id=row.symbol_id, price_observation_id=row.observation_id,
        price_observation_identity_snapshot_id=identity.snapshot_id if identity is not None else None,
        provider_symbol_mapping_id=identity.provider_mapping_id if identity is not None else None,
        provider=row.provider, provider_symbol=row.provider_symbol,
        adjustment_type=row.adjustment_type, parser_version=row.parser_version,
        close=row.close, volume=row.volume, observed_at=row.observed_at, payload_hash=row.payload_hash,
        mapping_status=identity.mapping_status if identity is not None else None,
        mapping_valid_from=identity.valid_from if identity is not None else None,
        mapping_valid_to=identity.valid_to if identity is not None else None,
        resolver_version=identity.resolver_version if identity is not None else None,
        resolved_at=identity.resolved_at if identity is not None else None,
        correction_ids=list(row.correction_ids),
        validation_evidence=[case.fingerprint_material() for case in row.validation_cases],
        input_status=row.input_status.value,
        reason_code=row.reason_code.value if row.reason_code is not None else None,
    )


def _comparison_material(value):
    """Hashable equality key, independent of PostgreSQL's durable fingerprint."""
    if isinstance(value, Decimal) and not value.is_finite():
        # Decimal NaN is unequal to itself; preserve its representation for reuse.
        return ("nonfinite_decimal", str(value))
    if isinstance(value, datetime):
        return _as_utc(value)
    if isinstance(value, dict):
        return tuple((key, _comparison_material(item)) for key, item in sorted(value.items()))
    if isinstance(value, (tuple, list)):
        return tuple(_comparison_material(item) for item in value)
    return value
