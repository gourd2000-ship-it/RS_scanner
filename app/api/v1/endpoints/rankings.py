from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.cache import cached_rankings
from app.core.database import get_db_session
from app.repositories.rs_repository import RsRepository
from app.schemas.query import RsSortField, SortOrder
from app.schemas.response import RsRankingItem, RsRankingResponse


router = APIRouter()


@router.get("/rankings/rs", response_model=RsRankingResponse)
@cached_rankings
def get_rankings(
    market: str = Query(..., pattern="^(KOSPI|KOSDAQ)$", description="시장 구분 (KOSPI/KOSDAQ)"),
    page: int = Query(default=1, ge=1, description="페이지 번호"),
    size: int = Query(default=100, ge=1, le=500, description="페이지 크기"),
    min_rs: int | None = Query(default=None, ge=1, le=99, description="최소 RS Rating"),
    max_rs: int | None = Query(default=None, ge=1, le=99, description="최대 RS Rating"),
    sort_by: RsSortField = Query(default=RsSortField.RANK_IN_MARKET, description="정렬 기준"),
    order: SortOrder = Query(default=SortOrder.ASC, description="정렬 방향"),
    trade_date: date | None = Query(default=None, description="조회 기준일 (기본값: 최신 거래일)"),
    exclude_etf: bool = Query(default=False, description="ETF 제외 여부"),
    sector: str | None = Query(default=None, description="섹터 필터 (semiconductor, auto, energy, ...)"),
    search: str | None = Query(default=None, min_length=1, max_length=100, description="종목명/코드 검색"),
    session: Session = Depends(get_db_session),
):
    """RS 랭킹 조회.

    시장별 상대 강도 순위를 종목명, 최신 가격과 함께 반환합니다.
    페이지네이션을 지원하며, 기본 100개, 최대 500개까지 조회 가능합니다.

    필터링:
    - min_rs, max_rs: RS Rating 범위 필터링 (1~99)

    정렬:
    - sort_by: 정렬 기준 (rs_rating, rank_in_market, return_3m, return_6m, return_9m, return_12m, relative_return_score)
    - order: 정렬 방향 (asc, desc)

    캐시: 1시간 (production 환경에서만 활성화)
    """
    # RS Rating 범위 검증
    if min_rs is not None and max_rs is not None and min_rs > max_rs:
        raise HTTPException(status_code=400, detail="min_rs는 max_rs보다 클 수 없습니다")

    items_data, total_count, result_trade_date = RsRepository(session).list_market_with_prices(
        market=market,
        page=page,
        size=size,
        min_rs=min_rs,
        max_rs=max_rs,
        sort_by=sort_by.value,
        order=order.value,
        trade_date=trade_date,
        exclude_etf=exclude_etf,
        sector=sector,
        search=search,
    )

    items = [RsRankingItem(**item) for item in items_data]

    return RsRankingResponse(
        market=market,
        trade_date=result_trade_date,
        total_count=total_count,
        page=page,
        size=size,
        items=items,
    )
