"""Read contracts for the protected EMA operator endpoint."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class EmaPeriodValueResponse(BaseModel):
    """One fixed-period EMA result for a trading day.

    ``value`` deliberately remains a string.  EMA is calculated with Decimal
    and a JSON number would silently discard the calculation precision.
    """

    period: int = Field(description="EMA period; one of 5, 20, 50, 200")
    value: str | None
    status: str
    reason_code: str | None = None
    available_observations: int


class EmaDailyResponse(BaseModel):
    trade_date: date
    values: list[EmaPeriodValueResponse]


class EmaQueryResponse(BaseModel):
    """A page of the current immutable EMA generation for one instrument."""

    instrument_id: int
    code: str
    as_of: date
    calculated_at: datetime
    page: int
    size: int
    total_count: int
    items: list[EmaDailyResponse]
