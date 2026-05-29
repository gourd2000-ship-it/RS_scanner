"""종목 관련 API 엔드포인트."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.cache import cached_stock_detail
from app.core.database import get_db_session
from app.models.daily_price import DailyPrice
from app.models.rs_score import RsScore
from app.models.symbol import Symbol
from app.schemas.response import (
    DailyPriceItem,
    PaginatedResponse,
    RsScoreItem,
    RsSeriesResponse,
    SymbolDetailResponse,
    SymbolItem,
)

router = APIRouter()


@router.get("/{code}", response_model=SymbolDetailResponse)
@cached_stock_detail
def get_stock_detail(
    code: str,
    session: Session = Depends(get_db_session),
):
    """종목 상세 정보 조회.

    종목의 기본 정보, 최신 가격, 최신 RS 점수를 한 번의 쿼리로 반환합니다.

    캐시: 10분 (production 환경에서만 활성화)
    """
    from sqlalchemy import func, literal_column

    # 최신 가격 서브쿼리
    latest_price_subq = (
        select(
            DailyPrice.symbol_id,
            DailyPrice.trade_date.label("price_trade_date"),
            DailyPrice.open,
            DailyPrice.high,
            DailyPrice.low,
            DailyPrice.close,
            DailyPrice.volume,
            DailyPrice.change_rate,
            func.row_number().over(
                partition_by=DailyPrice.symbol_id,
                order_by=DailyPrice.trade_date.desc()
            ).label("price_rn"),
        )
        .subquery()
    )

    # 최신 RS 서브쿼리
    latest_rs_subq = (
        select(
            RsScore.symbol_id,
            RsScore.trade_date.label("rs_trade_date"),
            RsScore.rs_rating,
            RsScore.rank_in_market,
            RsScore.return_3m,
            RsScore.return_6m,
            RsScore.return_9m,
            RsScore.return_12m,
            RsScore.relative_return_score,
            RsScore.rs_percentile,
            func.row_number().over(
                partition_by=RsScore.symbol_id,
                order_by=RsScore.trade_date.desc()
            ).label("rs_rn"),
        )
        .subquery()
    )

    # 메인 쿼리: Symbol + 최신 가격 + 최신 RS
    result = session.execute(
        select(
            Symbol,
            latest_price_subq.c.price_trade_date,
            latest_price_subq.c.open,
            latest_price_subq.c.high,
            latest_price_subq.c.low,
            latest_price_subq.c.close,
            latest_price_subq.c.volume,
            latest_price_subq.c.change_rate,
            latest_rs_subq.c.rs_trade_date,
            latest_rs_subq.c.rs_rating,
            latest_rs_subq.c.rank_in_market,
            latest_rs_subq.c.return_3m,
            latest_rs_subq.c.return_6m,
            latest_rs_subq.c.return_9m,
            latest_rs_subq.c.return_12m,
            latest_rs_subq.c.relative_return_score,
            latest_rs_subq.c.rs_percentile,
        )
        .outerjoin(
            latest_price_subq,
            (latest_price_subq.c.symbol_id == Symbol.id) & (latest_price_subq.c.price_rn == 1)
        )
        .outerjoin(
            latest_rs_subq,
            (latest_rs_subq.c.symbol_id == Symbol.id) & (latest_rs_subq.c.rs_rn == 1)
        )
        .where(Symbol.code == code)
    ).first()

    if result is None:
        raise HTTPException(status_code=404, detail=f"종목을 찾을 수 없습니다: {code}")

    symbol = result[0]

    # 종목 기본 정보
    symbol_item = SymbolItem(
        code=symbol.code,
        name=symbol.name,
        market=symbol.market,
        sector=symbol.sector,
        industry=symbol.industry,
        is_active=symbol.is_active,
        listed_at=symbol.listed_at,
    )

    # 최신 가격
    latest_price = None
    if result[1] is not None:  # price_trade_date
        latest_price = DailyPriceItem(
            trade_date=result[1],
            open=result[2],
            high=result[3],
            low=result[4],
            close=result[5],
            volume=result[6],
            change_rate=result[7],
        )

    # 최신 RS
    latest_rs = None
    if result[8] is not None:  # rs_trade_date
        latest_rs = RsScoreItem(
            trade_date=result[8],
            rs_rating=result[9],
            rank_in_market=result[10],
            return_3m=result[11],
            return_6m=result[12],
            return_9m=result[13],
            return_12m=result[14],
            relative_return_score=result[15],
            rs_percentile=result[16],
        )

    return SymbolDetailResponse(
        symbol=symbol_item,
        latest_price=latest_price,
        latest_rs=latest_rs,
        benchmark_name=symbol.market,
    )


@router.get("/{code}/rs-history", response_model=RsSeriesResponse)
def get_rs_history(
    code: str,
    limit: int = Query(default=90, ge=1, le=365, description="조회할 데이터 개수 (최대 365일)"),
    session: Session = Depends(get_db_session),
):
    """종목의 RS 점수 이력 조회.

    최근 N일간의 RS 점수 변화를 반환합니다.
    """
    # 종목 조회
    symbol = session.scalar(select(Symbol).where(Symbol.code == code))
    if symbol is None:
        raise HTTPException(status_code=404, detail=f"종목을 찾을 수 없습니다: {code}")

    # RS 이력 조회
    rs_rows = session.scalars(
        select(RsScore)
        .where(RsScore.symbol_id == symbol.id)
        .order_by(desc(RsScore.trade_date))
        .limit(limit)
    ).all()

    # 날짜 오름차순으로 정렬
    rs_rows = sorted(rs_rows, key=lambda x: x.trade_date)

    rs_scores = [
        RsScoreItem(
            trade_date=row.trade_date,
            rs_rating=row.rs_rating,
            rank_in_market=row.rank_in_market,
            return_3m=row.return_3m,
            return_6m=row.return_6m,
            return_9m=row.return_9m,
            return_12m=row.return_12m,
            relative_return_score=row.relative_return_score,
            rs_percentile=row.rs_percentile,
        )
        for row in rs_rows
    ]

    return RsSeriesResponse(
        code=symbol.code,
        name=symbol.name,
        market=symbol.market,
        rs_scores=rs_scores,
    )


@router.get("/{code}/prices", response_model=PaginatedResponse[DailyPriceItem])
def get_price_history(
    code: str,
    page: int = Query(default=1, ge=1, description="페이지 번호"),
    size: int = Query(default=100, ge=1, le=500, description="페이지 크기"),
    session: Session = Depends(get_db_session),
):
    """종목의 가격 데이터 조회.

    페이지네이션을 지원하며, 최신 데이터부터 반환합니다.
    """
    # 종목 조회
    symbol = session.scalar(select(Symbol).where(Symbol.code == code))
    if symbol is None:
        raise HTTPException(status_code=404, detail=f"종목을 찾을 수 없습니다: {code}")

    # 전체 개수 조회
    from sqlalchemy import func
    total_count = session.scalar(
        select(func.count()).select_from(DailyPrice).where(DailyPrice.symbol_id == symbol.id)
    ) or 0

    # 페이지네이션
    offset = (page - 1) * size
    price_rows = session.scalars(
        select(DailyPrice)
        .where(DailyPrice.symbol_id == symbol.id)
        .order_by(desc(DailyPrice.trade_date))
        .limit(size)
        .offset(offset)
    ).all()

    # 날짜 오름차순으로 정렬
    price_rows = sorted(price_rows, key=lambda x: x.trade_date)

    items = [
        DailyPriceItem(
            trade_date=row.trade_date,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
            change_rate=row.change_rate,
        )
        for row in price_rows
    ]

    return PaginatedResponse(
        total_count=total_count,
        page=page,
        size=size,
        items=items,
    )
