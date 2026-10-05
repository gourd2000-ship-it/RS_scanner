"""Volume MA50 persistence over the shared immutable input tables."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.indicator import (
    IndicatorCalculationRun, IndicatorInputEvidence, IndicatorInputPolicy,
    IndicatorRunInput, IndicatorSeries, IndicatorValue,
)
from app.repositories.indicator_repository import IndicatorRepository, _as_utc
from app.services.indicators.contracts import EmaInputRow, EmaSourcePolicy, canonical_json
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
        # Copy the same selection facts as EMA, into a run-independent row.
        snapshot = self._input_snapshot(IndicatorCalculationRun(), row, "")
        fields = {
            column.name: getattr(snapshot, column.name)
            for column in IndicatorInputEvidence.__table__.columns
            if column.name not in {"id", "input_policy_id", "evidence_key", "created_at"}
        }
        fields["input_policy_id"] = input_policy_id

        def material(values):
            return canonical_json({key: _as_utc(value) if isinstance(value, datetime) else value
                                   for key, value in values.items()})

        expected = material(fields)

        def find():
            candidates = self.session.scalars(select(IndicatorInputEvidence).where(
                IndicatorInputEvidence.input_policy_id == input_policy_id,
                IndicatorInputEvidence.instrument_id == row.instrument_id,
                IndicatorInputEvidence.trade_date == row.trade_date,
            ))
            return next((candidate for candidate in candidates if material(
                {key: getattr(candidate, key) for key in fields}) == expected), None)

        existing = find()
        if existing is not None:
            return existing
        try:
            with self.session.begin_nested():
                evidence = IndicatorInputEvidence(**fields)
                self.session.add(evidence)
                self.session.flush()  # Always read the server-generated evidence key.
                return evidence
        except IntegrityError:
            existing = find()
            if existing is None:
                raise
            return existing

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
