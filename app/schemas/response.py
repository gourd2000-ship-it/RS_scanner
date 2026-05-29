"""API 응답 스키마."""

from datetime import date, datetime
from decimal import Decimal
from typing import Generic, TypeVar

from pydantic import BaseModel, Field


T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """페이지네이션 응답 래퍼."""
    total_count: int = Field(description="전체 항목 수")
    page: int = Field(description="현재 페이지 번호")
    size: int = Field(description="페이지 크기")
    items: list[T] = Field(description="조회 결과 항목 목록")


class SymbolItem(BaseModel):
    """종목 기본 정보."""
    code: str = Field(description="종목 코드")
    name: str = Field(description="종목명")
    market: str = Field(description="시장 구분 (KOSPI/KOSDAQ)")
    sector: str | None = Field(default=None, description="섹터")
    industry: str | None = Field(default=None, description="업종")
    is_active: bool = Field(description="상장 여부")
    listed_at: date | None = Field(default=None, description="상장일")


class RsRankingItem(BaseModel):
    """RS 랭킹 항목 (종목 정보 + RS 지표 + 최신 가격)."""
    # 종목 정보
    code: str = Field(description="종목 코드")
    name: str = Field(description="종목명")
    market: str = Field(description="시장 구분")

    # RS 지표
    trade_date: date = Field(description="기준일")
    rs_rating: int = Field(description="RS Rating (1~99)")
    rank_in_market: int = Field(description="시장 내 순위")
    return_3m: Decimal = Field(description="3개월 상대 수익률")
    return_6m: Decimal = Field(description="6개월 상대 수익률")
    return_9m: Decimal = Field(description="9개월 상대 수익률")
    return_12m: Decimal = Field(description="12개월 상대 수익률")
    relative_return_score: Decimal = Field(description="가중 상대 수익률 점수")

    # 최신 가격 정보
    close: Decimal = Field(description="종가")
    change_rate: Decimal = Field(description="등락률")


class RsRankingResponse(BaseModel):
    """RS 랭킹 응답 (하위 호환성 유지)."""
    market: str = Field(description="시장 구분")
    trade_date: date | None = Field(default=None, description="기준일")
    total_count: int = Field(description="전체 항목 수")
    page: int = Field(description="현재 페이지 번호")
    size: int = Field(description="페이지 크기")
    items: list[RsRankingItem] = Field(description="랭킹 항목 목록")


class DailyPriceItem(BaseModel):
    """일봉 가격 정보."""
    trade_date: date = Field(description="거래일")
    open: Decimal = Field(description="시가")
    high: Decimal = Field(description="고가")
    low: Decimal = Field(description="저가")
    close: Decimal = Field(description="종가")
    volume: int = Field(description="거래량")
    change_rate: Decimal = Field(description="등락률")


class RsScoreItem(BaseModel):
    """RS 점수 항목."""
    trade_date: date = Field(description="기준일")
    rs_rating: int = Field(description="RS Rating (1~99)")
    rank_in_market: int = Field(description="시장 내 순위")
    return_3m: Decimal = Field(description="3개월 상대 수익률")
    return_6m: Decimal = Field(description="6개월 상대 수익률")
    return_9m: Decimal = Field(description="9개월 상대 수익률")
    return_12m: Decimal = Field(description="12개월 상대 수익률")
    relative_return_score: Decimal = Field(description="가중 상대 수익률 점수")
    rs_percentile: Decimal = Field(description="백분위 (0~1)")


class SymbolDetailResponse(BaseModel):
    """종목 상세 정보 응답."""
    # 종목 기본 정보
    symbol: SymbolItem = Field(description="종목 정보")

    # 최신 가격
    latest_price: DailyPriceItem | None = Field(default=None, description="최신 가격 정보")

    # 최신 RS
    latest_rs: RsScoreItem | None = Field(default=None, description="최신 RS 정보")

    # 벤치마크 정보
    benchmark_name: str | None = Field(default=None, description="벤치마크 이름 (KOSPI/KOSDAQ)")


class PriceSeriesResponse(BaseModel):
    """가격 시계열 응답."""
    code: str = Field(description="종목 코드")
    name: str = Field(description="종목명")
    prices: list[DailyPriceItem] = Field(description="가격 데이터")


class RsSeriesResponse(BaseModel):
    """RS 시계열 응답."""
    code: str = Field(description="종목 코드")
    name: str = Field(description="종목명")
    market: str = Field(description="시장 구분")
    rs_scores: list[RsScoreItem] = Field(description="RS 데이터")


class JobStatusResponse(BaseModel):
    """배치 작업 상태 응답."""
    job_type: str = Field(description="작업 유형")
    started_at: datetime = Field(description="시작 시각")
    finished_at: datetime | None = Field(default=None, description="종료 시각")
    status: str = Field(description="상태 (running/completed/failed)")
    symbols_total: int = Field(description="전체 종목 수")
    symbols_succeeded: int = Field(description="성공 종목 수")
    symbols_failed: int = Field(description="실패 종목 수")
    message: str | None = Field(default=None, description="메시지")


class HealthResponse(BaseModel):
    """헬스체크 응답."""
    status: str = Field(description="서비스 상태 (ok/degraded/error)")
    db_connected: bool = Field(description="DB 연결 상태")
    last_batch_at: datetime | None = Field(default=None, description="최근 배치 실행 시각")
    last_batch_status: str | None = Field(default=None, description="최근 배치 상태")
