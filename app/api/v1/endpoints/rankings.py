from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.cache import cached_rankings
from app.core.database import get_db_session
from app.repositories.rs_repository import RsRepository
from app.schemas.response import RsRankingItem, RsRankingResponse


router = APIRouter()


@router.get("/rankings/rs", response_model=RsRankingResponse)
@cached_rankings
def get_rankings(
    market: str = Query(..., pattern="^(KOSPI|KOSDAQ)$", description="시장 구분 (KOSPI/KOSDAQ)"),
    page: int = Query(default=1, ge=1, description="페이지 번호"),
    size: int = Query(default=100, ge=1, le=500, description="페이지 크기"),
    session: Session = Depends(get_db_session),
):
    """RS 랭킹 조회.

    시장별 상대 강도 순위를 종목명, 최신 가격과 함께 반환합니다.
    페이지네이션을 지원하며, 기본 100개, 최대 500개까지 조회 가능합니다.

    캐시: 1시간 (production 환경에서만 활성화)
    """
    items_data, total_count, trade_date = RsRepository(session).list_market_with_prices(
        market=market, page=page, size=size
    )

    items = [RsRankingItem(**item) for item in items_data]

    return RsRankingResponse(
        market=market,
        trade_date=trade_date,
        total_count=total_count,
        page=page,
        size=size,
        items=items,
    )
