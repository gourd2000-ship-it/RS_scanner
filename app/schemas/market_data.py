from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class SymbolPayload(BaseModel):
    code: str
    name: str
    market: str
    symbol_type: str = "stock"


class DailyPricePayload(BaseModel):
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    change_rate: Decimal


class BenchmarkPricePayload(BaseModel):
    benchmark_code: str
    market: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int | None = None
    change_rate: Decimal


class RsResultPayload(BaseModel):
    code: str
    market: str
    trade_date: date
    return_3m: Decimal
    return_6m: Decimal
    return_9m: Decimal
    return_12m: Decimal
    relative_return_score: Decimal
    rs_percentile: Decimal
    rs_rating: int
    rank_in_market: int


class JobStatusPayload(BaseModel):
    job_type: str
    started_at: datetime
    status: str
    symbols_total: int
    symbols_succeeded: int
    symbols_failed: int
