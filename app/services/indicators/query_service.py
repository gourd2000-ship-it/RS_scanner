"""Protected read model for persisted current-generation EMA values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.repositories.indicator_repository import CurrentEmaMetadata, EmaStoredValue, IndicatorRepository
from app.services.indicators.contracts import EMA_PERIODS


class EmaQueryError(ValueError):
    """Base class for query errors which the HTTP layer maps deliberately."""


class UnknownInstrumentError(EmaQueryError):
    pass


class AmbiguousInstrumentCodeError(EmaQueryError):
    pass


class EmaNotCalculatedError(EmaQueryError):
    pass


@dataclass(frozen=True)
class EmaPeriodValue:
    period: int
    value: Decimal | None
    status: str
    reason_code: str | None
    available_observations: int


@dataclass(frozen=True)
class EmaDailyValue:
    trade_date: date
    values: tuple[EmaPeriodValue, ...]


@dataclass(frozen=True)
class EmaQueryPage:
    instrument_id: int
    code: str
    as_of: date
    calculated_at: datetime
    page: int
    size: int
    total_count: int
    items: tuple[EmaDailyValue, ...]


class EmaQueryService:
    """Resolves an historical instrument then reads its current EMA lineage.

    A code is only a lookup aid.  The persisted series belongs to a canonical
    Instrument, so an ambiguous historical code must be disambiguated by the
    caller's instrument ID instead of selecting a current Symbol arbitrarily.
    """

    def __init__(self, session: Session) -> None:
        self.repository = IndicatorRepository(session)

    def current_page(
        self,
        *,
        code: str,
        instrument_id: int | None,
        start: date,
        end: date,
        page: int,
        size: int,
    ) -> EmaQueryPage:
        if not code.strip():
            raise EmaQueryError("code must not be blank")
        if start > end:
            raise EmaQueryError("start must not be after end")

        resolved = self._resolve_instrument(code=code.strip(), instrument_id=instrument_id)
        metadata = self.repository.current_ema_metadata(instrument_id=resolved.id)
        if metadata is None:
            raise EmaNotCalculatedError("current EMA generation is unavailable")

        rows, total_count = self.repository.current_ema_page(
            instrument_id=resolved.id,
            generation_id=metadata.generation_id,
            start=start,
            end=end,
            page=page,
            size=size,
        )
        return EmaQueryPage(
            instrument_id=resolved.id,
            code=code.strip(),
            as_of=metadata.as_of,
            calculated_at=metadata.calculated_at,
            page=page,
            size=size,
            total_count=total_count,
            items=self._group_rows(rows),
        )

    def _resolve_instrument(self, *, code: str, instrument_id: int | None):
        matches = self.repository.find_instruments_for_code(code=code)
        if instrument_id is None:
            if not matches:
                raise UnknownInstrumentError("instrument code was not found")
            if len(matches) != 1:
                raise AmbiguousInstrumentCodeError(
                    "code maps to multiple historical instruments; supply instrument_id"
                )
            return matches[0]

        selected = self.repository.get_instrument(instrument_id)
        if selected is None or all(item.id != instrument_id for item in matches):
            raise UnknownInstrumentError("instrument_id does not identify the requested code")
        return selected

    @staticmethod
    def _group_rows(rows: tuple[EmaStoredValue, ...]) -> tuple[EmaDailyValue, ...]:
        values_by_date: dict[date, list[EmaPeriodValue]] = {}
        for row in rows:
            values_by_date.setdefault(row.trade_date, []).append(
                EmaPeriodValue(
                    period=row.period,
                    value=row.value,
                    status=row.status,
                    reason_code=row.reason_code,
                    available_observations=row.available_observations,
                )
            )
        daily: list[EmaDailyValue] = []
        for trade_date, values in values_by_date.items():
            # A completed run carries all fixed periods.  Preserve that contract
            # at the read boundary, rather than making a shorter period list
            # look like a complete daily EMA result.
            if tuple(value.period for value in values) != EMA_PERIODS:
                raise RuntimeError("current EMA generation has an incomplete period set")
            daily.append(EmaDailyValue(trade_date=trade_date, values=tuple(values)))
        return tuple(daily)
