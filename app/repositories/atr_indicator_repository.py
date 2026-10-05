"""ATR14 runs reuse immutable OHLCV policy/evidence and generation locking."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.indicator import (
    IndicatorCalculationRun, IndicatorInputEvidence, IndicatorRunInput,
    IndicatorSeries, IndicatorValue,
)
from app.repositories.volume_indicator_repository import VolumeIndicatorRepository
from app.services.indicators.atr import ATR_PERIOD, AtrResult
from app.services.indicators.contracts import EmaSourcePolicy, canonical_json


class AtrIndicatorRepository(VolumeIndicatorRepository):
    """Share selection evidence with Volume without writing either other series."""

    def get_or_create_series(self, *, instrument_id: int, policy: EmaSourcePolicy) -> IndicatorSeries:
        common = self.get_or_create_policy(policy)

        def find():
            return self.session.scalar(select(IndicatorSeries).where(
                IndicatorSeries.instrument_id == instrument_id,
                IndicatorSeries.indicator_kind == "atr",
                IndicatorSeries.input_policy_id == common.id,
            ))

        existing = find()
        if existing is not None:
            return existing
        try:
            with self.session.begin_nested():
                row = IndicatorSeries(
                    instrument_id=instrument_id, indicator_kind="atr",
                    input_field="high-low-close", periods="14", formula_version="wilder-atr-14-v1",
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

    def complete_atr_run(
        self, *, run: IndicatorCalculationRun, evidence: Sequence[IndicatorInputEvidence],
        prefix_hashes: Sequence[str], result: AtrResult,
    ) -> None:
        self.assert_run_running(run)
        dates = tuple(row.trade_date for row in evidence)
        if (not dates or len(set(dates)) != len(dates) or len(evidence) != len(prefix_hashes)
                or tuple(value.trade_date for value in result.values) != dates):
            raise ValueError("every ATR input date must have exactly one matching value and prefix")
        series = self.session.get(IndicatorSeries, run.series_id)
        if series is None or series.indicator_kind != "atr" or any(
            row.instrument_id != series.instrument_id or row.input_policy_id != series.input_policy_id
            for row in evidence
        ):
            raise ValueError("ATR run evidence must match its series instrument and policy")
        expected_hash = sha256(canonical_json(
            [value.material() for value in result.values]).encode("utf-8")).hexdigest()
        if result.result_hash != expected_hash:
            raise ValueError("ATR result hash must match its exact calculator values")
        self.session.add_all([
            IndicatorRunInput(calculation_run_id=run.id, evidence_id=row.id,
                              ordinal=ordinal, prefix_hash=prefix)
            for ordinal, (row, prefix) in enumerate(zip(evidence, prefix_hashes, strict=True))
        ])
        self.session.add_all([
            IndicatorValue(
                calculation_run_id=run.id, generation_id=run.generation_id,
                indicator_kind="atr", period=ATR_PERIOD, trade_date=value.trade_date,
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
