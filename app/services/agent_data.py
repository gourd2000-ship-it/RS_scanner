"""Hermes Agent facade가 공유하는 freshness와 read-only query 서비스."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.crawl_job import CrawlJob
from app.models.daily_price import DailyPrice
from app.models.rs_score import RsScore
from app.models.symbol import Symbol
from app.schemas.agent import (
    AgentMeta,
    AgentRankingItem,
    AgentRankingPage,
    AgentStatusData,
    AgentStockHistoryData,
    AgentStockSnapshotData,
)
from app.schemas.response import DailyPriceItem, RsScoreItem


@dataclass(frozen=True)
class AgentDataMeta:
    dataset_id: str
    trade_date: date | None
    as_of: datetime | None
    data_status: str
    coverage: float

    def as_schema(self, request_id: str | None = None) -> AgentMeta:
        return AgentMeta(
            dataset_id=self.dataset_id,
            trade_date=self.trade_date,
            as_of=self.as_of,
            data_status=self.data_status,
            coverage=self.coverage,
            request_id=request_id,
        )


def build_agent_meta(
    session: Session,
    *,
    now: datetime | None = None,
) -> AgentDataMeta:
    now = now or datetime.utcnow()
    settings = get_settings()
    latest_job = session.scalar(
        select(CrawlJob)
        .where(CrawlJob.job_type == "daily_full")
        .order_by(desc(CrawlJob.started_at))
        .limit(1)
    )
    latest_price_date = session.scalar(select(func.max(DailyPrice.trade_date)))
    latest_rs_date = session.scalar(select(func.max(RsScore.trade_date)))
    if latest_price_date is not None and latest_rs_date is not None:
        trade_date = min(latest_price_date, latest_rs_date)
    else:
        trade_date = latest_rs_date or latest_price_date
    has_any_dataset = latest_price_date is not None or latest_rs_date is not None
    has_complete_dataset = (
        latest_price_date is not None
        and latest_rs_date is not None
        and latest_price_date == latest_rs_date
    )

    coverage = 0.0
    if latest_job is not None and latest_job.symbols_total:
        coverage = max(
            0.0,
            min(1.0, latest_job.symbols_succeeded / latest_job.symbols_total),
        )

    as_of = None
    if latest_job is not None:
        as_of = latest_job.finished_at or latest_job.started_at

    if latest_job is None or not has_any_dataset:
        data_status = "unavailable"
    elif latest_job.status == "completed_with_errors":
        data_status = "partial"
    elif latest_job.status == "completed" and has_complete_dataset:
        data_status = "complete"
    elif latest_job.status == "completed":
        data_status = "partial"
    else:
        data_status = "unavailable"

    if (
        data_status in {"complete", "partial"}
        and as_of is not None
        and now - as_of > timedelta(hours=settings.agent_freshness_max_age_hours)
    ):
        data_status = "stale"

    dataset_id = (
        f"rs-{latest_job.id}-{trade_date.isoformat()}"
        if latest_job is not None and trade_date is not None
        else "rs-unavailable"
    )
    return AgentDataMeta(
        dataset_id=dataset_id,
        trade_date=trade_date,
        as_of=as_of,
        data_status=data_status,
        coverage=coverage,
    )


def get_status_data(session: Session) -> AgentStatusData:
    latest_job = session.scalar(
        select(CrawlJob)
        .where(CrawlJob.job_type == "daily_full")
        .order_by(desc(CrawlJob.started_at))
        .limit(1)
    )
    return AgentStatusData(
        service="rs-scanner",
        latest_job_id=latest_job.id if latest_job is not None else None,
        latest_job_status=latest_job.status if latest_job is not None else None,
        latest_price_trade_date=session.scalar(select(func.max(DailyPrice.trade_date))),
        latest_rs_trade_date=session.scalar(select(func.max(RsScore.trade_date))),
    )


def get_rs_rankings(
    session: Session,
    *,
    market: str,
    trade_date: date,
    page: int,
    size: int,
) -> AgentRankingPage:
    filters = [
        RsScore.market == market,
        RsScore.trade_date == trade_date,
        Symbol.is_active.is_(True),
        Symbol.symbol_type == "stock",
    ]
    total_count = session.scalar(
        select(func.count())
        .select_from(RsScore)
        .join(Symbol, Symbol.id == RsScore.symbol_id)
        .where(*filters)
    ) or 0
    rows = session.execute(
        select(RsScore, Symbol.code, Symbol.name)
        .join(Symbol, Symbol.id == RsScore.symbol_id)
        .where(*filters)
        .order_by(RsScore.rank_in_market)
        .limit(size)
        .offset((page - 1) * size)
    ).all()
    items = [
        AgentRankingItem(
            code=code,
            name=name,
            market=row.market,
            trade_date=row.trade_date,
            rs_rating=row.rs_rating,
            rank_in_market=row.rank_in_market,
            return_1m=row.return_1m,
            return_3m=row.return_3m,
            return_6m=row.return_6m,
            return_9m=row.return_9m,
            return_12m=row.return_12m,
            rs_1m=row.rs_1m,
            rs_3m=row.rs_3m,
            rs_6m=row.rs_6m,
            rs_12m=row.rs_12m,
            relative_return_score=row.relative_return_score,
            rs_percentile=row.rs_percentile,
        )
        for row, code, name in rows
    ]
    return AgentRankingPage(
        market=market,
        trade_date=trade_date,
        total_count=total_count,
        page=page,
        size=size,
        items=items,
    )


def get_briefing_data(
    session: Session,
    *,
    trade_date: date,
    size: int = 10,
) -> dict[str, list[AgentRankingItem]]:
    return {
        market: get_rs_rankings(
            session,
            market=market,
            trade_date=trade_date,
            page=1,
            size=size,
        ).items
        for market in ("KOSPI", "KOSDAQ")
    }


def get_stock_snapshot(
    session: Session,
    *,
    code: str,
    trade_date: date | None,
) -> AgentStockSnapshotData:
    symbol = session.scalar(select(Symbol).where(Symbol.code == code))
    if symbol is None:
        raise LookupError(code)

    price_filters = [DailyPrice.symbol_id == symbol.id]
    rs_filters = [RsScore.symbol_id == symbol.id]
    if trade_date is not None:
        price_filters.append(DailyPrice.trade_date <= trade_date)
        rs_filters.append(RsScore.trade_date <= trade_date)

    price = session.scalar(
        select(DailyPrice)
        .where(*price_filters)
        .order_by(desc(DailyPrice.trade_date))
        .limit(1)
    )
    rs = session.scalar(
        select(RsScore)
        .where(*rs_filters)
        .order_by(desc(RsScore.trade_date))
        .limit(1)
    )

    latest_price = (
        DailyPriceItem(
            trade_date=price.trade_date,
            open=price.open,
            high=price.high,
            low=price.low,
            close=price.close,
            volume=price.volume,
            change_rate=price.change_rate,
            source=price.source,
        )
        if price is not None
        else None
    )
    latest_rs = (
        RsScoreItem(
            trade_date=rs.trade_date,
            rs_rating=rs.rs_rating,
            rank_in_market=rs.rank_in_market,
            return_1m=rs.return_1m,
            return_3m=rs.return_3m,
            return_6m=rs.return_6m,
            return_9m=rs.return_9m,
            return_12m=rs.return_12m,
            relative_return_score=rs.relative_return_score,
            rs_1m=rs.rs_1m,
            rs_3m=rs.rs_3m,
            rs_6m=rs.rs_6m,
            rs_12m=rs.rs_12m,
            rs_percentile=rs.rs_percentile,
        )
        if rs is not None
        else None
    )
    return AgentStockSnapshotData(
        code=symbol.code,
        name=symbol.name,
        market=symbol.market,
        symbol_type=symbol.symbol_type,
        is_active=symbol.is_active,
        latest_price=latest_price,
        latest_rs=latest_rs,
    )


def get_stock_history(
    session: Session,
    *,
    code: str,
    trade_date: date | None,
    limit: int,
) -> AgentStockHistoryData:
    symbol = session.scalar(select(Symbol).where(Symbol.code == code))
    if symbol is None:
        raise LookupError(code)

    filters = [DailyPrice.symbol_id == symbol.id]
    if trade_date is not None:
        filters.append(DailyPrice.trade_date <= trade_date)
    rows = session.scalars(
        select(DailyPrice)
        .where(*filters)
        .order_by(desc(DailyPrice.trade_date))
        .limit(limit)
    ).all()
    rows = sorted(rows, key=lambda row: row.trade_date)
    return AgentStockHistoryData(
        code=symbol.code,
        name=symbol.name,
        market=symbol.market,
        prices=[
            DailyPriceItem(
                trade_date=row.trade_date,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
                change_rate=row.change_rate,
                source=row.source,
            )
            for row in rows
        ],
    )
