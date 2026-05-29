"""API 쿼리 파라미터 스키마."""

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class MarketType(str, Enum):
    """시장 구분."""
    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"


class SortOrder(str, Enum):
    """정렬 순서."""
    ASC = "asc"
    DESC = "desc"


class RsSortField(str, Enum):
    """RS 랭킹 정렬 필드."""
    RS_RATING = "rs_rating"
    RANK_IN_MARKET = "rank_in_market"
    RETURN_3M = "return_3m"
    RETURN_6M = "return_6m"
    RETURN_9M = "return_9m"
    RETURN_12M = "return_12m"


class PaginationParams(BaseModel):
    """페이지네이션 파라미터."""
    page: int = Field(default=1, ge=1, description="페이지 번호 (1부터 시작)")
    size: int = Field(default=50, ge=1, le=200, description="페이지 크기 (최대 200)")


class SymbolListQuery(PaginationParams):
    """종목 목록 조회 쿼리."""
    market: MarketType | None = Field(default=None, description="시장 구분 (KOSPI/KOSDAQ)")
    is_active: bool | None = Field(default=None, description="상장 여부")
    search: str | None = Field(default=None, max_length=100, description="종목명 또는 종목코드 검색")


class RsRankingQuery(PaginationParams):
    """RS 랭킹 조회 쿼리."""
    market: MarketType = Field(description="시장 구분 (KOSPI/KOSDAQ)")
    trade_date: date | None = Field(default=None, description="기준일 (기본값: 최신 거래일)")
    min_rs: int | None = Field(default=None, ge=1, le=99, description="최소 RS Rating")
    max_rs: int | None = Field(default=None, ge=1, le=99, description="최대 RS Rating")
    sort_by: RsSortField = Field(default=RsSortField.RS_RATING, description="정렬 기준")
    order: SortOrder = Field(default=SortOrder.DESC, description="정렬 순서")


class PriceSeriesQuery(BaseModel):
    """가격 시계열 조회 쿼리."""
    start_date: date | None = Field(default=None, description="시작일")
    end_date: date | None = Field(default=None, description="종료일")
    limit: int = Field(default=252, ge=1, le=1000, description="최대 조회 건수")


class RsSeriesQuery(BaseModel):
    """RS 시계열 조회 쿼리."""
    start_date: date | None = Field(default=None, description="시작일")
    end_date: date | None = Field(default=None, description="종료일")
    limit: int = Field(default=252, ge=1, le=1000, description="최대 조회 건수")
