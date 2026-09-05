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
    return_1m: Decimal | None = None
    return_3m: Decimal
    return_6m: Decimal
    return_9m: Decimal
    return_12m: Decimal
    rs_1m: int = 0
    rs_3m: int = 0
    rs_6m: int = 0
    rs_12m: int = 0
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


class BacktestUniverseState(BaseModel):
    """가격 행 시점에 검증 가능한 유니버스 상태.

    과거 snapshot이 없으면 현재 ``Symbol.is_active``를 역사적 상태로 추정하지 않고
    ``unknown``으로 표현한다.
    """

    status: Literal[
        "listed_observed",
        "delisted_recorded",
        "not_listed_recorded",
        "unknown",
    ]
    observed_as_of: date | None = None
    source: str | None = None
    trading_status: str | None = None


class BacktestDatasetItem(BaseModel):
    code: str
    name: str
    market: str
    trade_date: date
    price: DailyPriceItem
    rs: RsScoreItem | None = None
    universe: BacktestUniverseState


class BacktestCoverage(BaseModel):
    """현재 페이지에서 해당 보조 데이터가 제공된 비율."""

    rs: float = Field(ge=0, le=1)
    universe: float = Field(ge=0, le=1)


class BacktestWatermark(BaseModel):
    """데이터셋을 구성한 각 원본 테이블의 최대 식별자."""

    daily_price_id: int
    rs_score_id: int
    universe_snapshot_id: int


class BacktestDatasetResponse(BaseModel):
    dataset_id: str
    watermark: BacktestWatermark
    coverage: BacktestCoverage
    next_cursor: str | None = None
    items: list[BacktestDatasetItem]
