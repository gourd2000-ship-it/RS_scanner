"""Operator read model for current Volume MA50 and ATR14 generations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.repositories.backtest_indicator_query_repository import (
    BacktestIndicatorQueryRepository,
    CurrentIndicatorSeries,
    IndicatorStoredValue,
)


class IndicatorQueryError(ValueError):
    """Base class for request errors mapped by the API boundary."""


class UnknownIndicatorInstrumentError(IndicatorQueryError):
    pass


class IndicatorInstrumentMismatchError(IndicatorQueryError):
    pass


class AmbiguousIndicatorInstrumentError(IndicatorQueryError):
    def __init__(self, *, code: str, instrument_ids: tuple[int, ...]) -> None:
        self.detail = {
            "reason": "ambiguous_instrument_code",
            "code": code,
            "instrument_ids": list(instrument_ids),
        }
        super().__init__("code maps to multiple historical instruments; supply instrument_id")


class AmbiguousCurrentIndicatorSeriesError(IndicatorQueryError):
    def __init__(
        self,
        *,
        instrument_id: int,
        indicator_kind: str,
        series: tuple[CurrentIndicatorSeries, ...],
    ) -> None:
        self.detail = {
            "reason": "ambiguous_current_source_policy",
            "instrument_id": instrument_id,
            "indicator_kind": indicator_kind,
            "series_ids": [item.series_id for item in series],
            "input_policy_ids": [item.input_policy.id for item in series],
        }
        super().__init__("multiple current source policies exist; supply series_id")


class IndicatorNotCalculatedError(IndicatorQueryError):
    pass


@dataclass(frozen=True)
class IndicatorQueryPage:
    indicator_kind: str
    code: str
    instrument_id: int
    series: CurrentIndicatorSeries
    page: int
    size: int
    total_count: int
    items: tuple[IndicatorStoredValue, ...]


class BacktestIndicatorQueryService:
    """Resolve stable identity and read exactly one current policy generation."""

    _KINDS = frozenset({"volume_sma", "atr"})

    def __init__(self, session: Session) -> None:
        self.repository = BacktestIndicatorQueryRepository(session)

    def current_page(
        self,
        *,
        indicator_kind: str,
        code: str,
        instrument_id: int | None,
        series_id: int | None,
        start: date,
        end: date,
        page: int,
        size: int,
    ) -> IndicatorQueryPage:
        normalized_code = code.strip()
        if not normalized_code:
            raise IndicatorQueryError("code must not be blank")
        if indicator_kind not in self._KINDS:
            raise IndicatorQueryError("unsupported indicator kind")
        if start > end:
            raise IndicatorQueryError("start must not be after end")
        if page < 1 or size < 1:
            raise IndicatorQueryError("page and size must be positive")

        matches = self.repository.find_instruments_for_code(code=normalized_code)
        if instrument_id is None:
            if not matches:
                raise UnknownIndicatorInstrumentError("instrument code was not found")
            if len(matches) > 1:
                raise AmbiguousIndicatorInstrumentError(
                    code=normalized_code,
                    instrument_ids=tuple(item.id for item in matches),
                )
            instrument = matches[0]
        else:
            instrument = self.repository.get_instrument(instrument_id)
            if instrument is None:
                raise UnknownIndicatorInstrumentError("instrument was not found")
            if all(item.id != instrument_id for item in matches):
                raise IndicatorInstrumentMismatchError(
                    "instrument_id does not identify the requested code"
                )

        if series_id is not None:
            requested_series = self.repository.find_series(
                instrument_id=instrument.id,
                series_id=series_id,
            )
            if (
                requested_series is None
                or requested_series.indicator_kind != indicator_kind
            ):
                raise IndicatorInstrumentMismatchError(
                    "series_id does not identify this instrument and indicator"
                )

        candidates = self.repository.current_series(
            instrument_id=instrument.id,
            indicator_kind=indicator_kind,
            series_id=series_id,
        )
        if not candidates:
            raise IndicatorNotCalculatedError("no calculated current indicator series is available")
        if len(candidates) > 1:
            raise AmbiguousCurrentIndicatorSeriesError(
                instrument_id=instrument.id,
                indicator_kind=indicator_kind,
                series=candidates,
            )
        selected = candidates[0]
        rows, total_count = self.repository.page(
            instrument_id=instrument.id,
            indicator_kind=indicator_kind,
            series_id=selected.series_id,
            generation_id=selected.generation_id,
            start=start,
            end=end,
            page=page,
            size=size,
        )
        return IndicatorQueryPage(
            indicator_kind=indicator_kind,
            code=normalized_code,
            instrument_id=instrument.id,
            series=selected,
            page=page,
            size=size,
            total_count=total_count,
            items=rows,
        )


def decimal_string(value: Decimal | None) -> str | None:
    """Serialize a Decimal without converting it through JSON floating point."""
    return format(value, "f") if value is not None else None
