"""Hermes Agent API의 공통 envelope와 읽기 모델."""

from datetime import date, datetime
from decimal import Decimal
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

from app.schemas.response import DailyPriceItem, RsScoreItem


AgentDataStatus = Literal["complete", "partial", "stale", "unavailable"]
T = TypeVar("T")


class AgentMeta(BaseModel):
    dataset_id: str
    trade_date: date | None = None
    as_of: datetime | None = None
    data_status: AgentDataStatus
    coverage: float = Field(ge=0, le=1)
    request_id: str | None = None


class AgentEnvelope(BaseModel, Generic[T]):
    data: T
    meta: AgentMeta


class AgentStatusData(BaseModel):
    service: str
    latest_job_id: int | None = None
    latest_job_status: str | None = None
    latest_price_trade_date: date | None = None
    latest_rs_trade_date: date | None = None


class AgentRankingItem(BaseModel):
    code: str
    name: str
    market: str
    trade_date: date
    rs_rating: int
    rank_in_market: int
    return_3m: Decimal
    return_6m: Decimal
    return_9m: Decimal
    return_12m: Decimal
    relative_return_score: Decimal
    rs_percentile: Decimal


class AgentRankingPage(BaseModel):
    market: str
    trade_date: date
    total_count: int
    page: int
    size: int
    items: list[AgentRankingItem]


class AgentBriefingData(BaseModel):
    trade_date: date
    rankings: dict[str, list[AgentRankingItem]]


class AgentStockSnapshotData(BaseModel):
    code: str
    name: str
    market: str
    symbol_type: str
    is_active: bool
    latest_price: DailyPriceItem | None = None
    latest_rs: RsScoreItem | None = None


class AgentStockHistoryData(BaseModel):
    code: str
    name: str
    market: str
    prices: list[DailyPriceItem]
