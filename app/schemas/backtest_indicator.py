"""Response contracts for the protected backtest indicator read API."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class IndicatorInputPolicyResponse(BaseModel):
    id: int
    version: str
    source_provider: str
    adjustment_policy: str
    allowed_parser_versions: list[str]
    observation_cutoff: datetime
    selector_version: str
    validation_version: str
    correction_version: str


class BacktestIndicatorDailyResponse(BaseModel):
    trade_date: date
    value: str | None
    status: str
    reason_code: str | None
    available_observations: int


class BacktestIndicatorQueryResponse(BaseModel):
    indicator_kind: str
    code: str
    instrument_id: int
    series_id: int
    generation_id: int
    generation: int
    period: int
    input_field: str
    formula_version: str
    source_provider: str
    adjustment_policy: str
    source_policy_fingerprint: str
    input_policy: IndicatorInputPolicyResponse
    as_of: date
    calculated_at: datetime
    page: int
    size: int
    total_count: int
    items: list[BacktestIndicatorDailyResponse]
