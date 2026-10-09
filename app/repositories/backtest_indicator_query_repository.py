"""Read-only persistence queries for current backtest indicator values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.indicator import (
    IndicatorCalculationRun,
    IndicatorGeneration,
    IndicatorInputPolicy,
    IndicatorSeries,
    IndicatorValue,
)
from app.models.instrument import Instrument
from app.models.symbol import Symbol


@dataclass(frozen=True)
class CurrentIndicatorSeries:
    series_id: int
    generation_id: int
    generation: int
    input_field: str
    periods: str
    formula_version: str
    source_provider: str
    adjustment_policy: str
    input_policy: IndicatorInputPolicy
    as_of: date
    calculated_at: datetime


@dataclass(frozen=True)
class IndicatorStoredValue:
    trade_date: date
    value: Decimal | None
    status: str
    reason_code: str | None
    available_observations: int


class BacktestIndicatorQueryRepository:
    """Read indicator lineage without exposing any mutation operation."""

    _KINDS = {
        "volume_sma": ("volume", 50, "volume-sma-v1"),
        "atr": ("high-low-close", 14, "wilder-atr-14-v1"),
    }

    def __init__(self, session: Session) -> None:
        self.session = session

    def find_instruments_for_code(self, *, code: str) -> tuple[Instrument, ...]:
        rows = self.session.scalars(
            select(Instrument)
            .outerjoin(Symbol, Symbol.instrument_id == Instrument.id)
            .where(
                (Instrument.krx_short_code == code)
                | (Symbol.code == code)
                | (Symbol.legacy_code == code)
            )
            .order_by(Instrument.id)
        ).unique()
        return tuple(rows)

    def get_instrument(self, instrument_id: int) -> Instrument | None:
        return self.session.get(Instrument, instrument_id)

    def find_series(self, *, instrument_id: int, series_id: int) -> IndicatorSeries | None:
        return self.session.scalar(
            select(IndicatorSeries).where(
                IndicatorSeries.id == series_id,
                IndicatorSeries.instrument_id == instrument_id,
            )
        )

    def current_series(
        self,
        *,
        instrument_id: int,
        indicator_kind: str,
        series_id: int | None = None,
    ) -> tuple[CurrentIndicatorSeries, ...]:
        definition = self._KINDS.get(indicator_kind)
        if definition is None:
            raise ValueError("unsupported indicator kind")
        input_field, period, formula_version = definition
        filters = [
            IndicatorSeries.instrument_id == instrument_id,
            IndicatorSeries.indicator_kind == indicator_kind,
            IndicatorSeries.input_field == input_field,
            IndicatorSeries.periods == str(period),
            IndicatorSeries.input_policy_version == "validated-observation-ohlcv-v1",
            IndicatorSeries.formula_version == formula_version,
            IndicatorGeneration.status == "current",
            IndicatorCalculationRun.status == "completed",
            IndicatorValue.indicator_kind == indicator_kind,
            IndicatorValue.period == period,
        ]
        if series_id is not None:
            filters.append(IndicatorSeries.id == series_id)

        rows = self.session.execute(
            select(
                IndicatorSeries.id,
                IndicatorGeneration.id,
                IndicatorGeneration.generation,
                IndicatorSeries.input_field,
                IndicatorSeries.periods,
                IndicatorSeries.formula_version,
                IndicatorSeries.source_provider,
                IndicatorSeries.adjustment_policy,
                IndicatorInputPolicy,
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
            .join(IndicatorInputPolicy, IndicatorInputPolicy.id == IndicatorSeries.input_policy_id)
            .where(*filters)
            .group_by(
                IndicatorSeries.id,
                IndicatorGeneration.id,
                IndicatorGeneration.generation,
                IndicatorSeries.input_field,
                IndicatorSeries.periods,
                IndicatorSeries.formula_version,
                IndicatorSeries.source_provider,
                IndicatorSeries.adjustment_policy,
                IndicatorInputPolicy.id,
            )
            .order_by(IndicatorSeries.id, IndicatorGeneration.generation)
        ).all()
        return tuple(
            CurrentIndicatorSeries(
                series_id=row[0],
                generation_id=row[1],
                generation=row[2],
                input_field=row[3],
                periods=row[4],
                formula_version=row[5],
                source_provider=row[6],
                adjustment_policy=row[7],
                input_policy=row[8],
                as_of=row[9],
                calculated_at=_as_utc(row[10]),
            )
            for row in rows
            if row[9] is not None and row[10] is not None
        )

    def page(
        self,
        *,
        instrument_id: int,
        indicator_kind: str,
        series_id: int,
        generation_id: int,
        start: date,
        end: date,
        page: int,
        size: int,
    ) -> tuple[tuple[IndicatorStoredValue, ...], int]:
        definition = self._KINDS[indicator_kind]
        input_field, period, formula_version = definition
        filters = (
            IndicatorSeries.instrument_id == instrument_id,
            IndicatorSeries.indicator_kind == indicator_kind,
            IndicatorSeries.input_field == input_field,
            IndicatorSeries.input_policy_version == "validated-observation-ohlcv-v1",
            IndicatorSeries.formula_version == formula_version,
            IndicatorSeries.id == series_id,
            IndicatorGeneration.id == generation_id,
            IndicatorGeneration.status == "current",
            IndicatorCalculationRun.status == "completed",
            IndicatorValue.indicator_kind == indicator_kind,
            IndicatorValue.period == period,
            IndicatorValue.trade_date >= start,
            IndicatorValue.trade_date <= end,
        )
        date_query = (
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
        total_count = self.session.scalar(
            select(func.count()).select_from(date_query.subquery())
        ) or 0
        trade_dates = tuple(
            self.session.scalars(date_query.offset((page - 1) * size).limit(size))
        )
        if not trade_dates:
            return (), total_count

        rows = tuple(
            self.session.execute(
                select(
                    IndicatorValue.trade_date,
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
                .order_by(IndicatorValue.trade_date, IndicatorCalculationRun.id)
            )
        )
        if len(rows) != len(trade_dates):
            raise RuntimeError("current indicator generation has duplicate values for a trade date")
        return (
            tuple(
                IndicatorStoredValue(
                    trade_date=row[0],
                    value=row[1],
                    status=row[2],
                    reason_code=row[3],
                    available_observations=row[4],
                )
                for row in rows
            ),
            total_count,
        )


def _as_utc(value: datetime) -> datetime:
    """Normalize database datetimes before returning public metadata."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
