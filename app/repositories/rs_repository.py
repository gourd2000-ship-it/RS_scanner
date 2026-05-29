from collections.abc import Iterable
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.benchmark import Benchmark
from app.models.rs_score import RsScore
from app.models.symbol import Symbol
from app.schemas.market_data import RsResultPayload
from app.services.rs.policy import MARKET_BENCHMARKS


class RsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_many(self, market: str, rows: Iterable[RsResultPayload]) -> list[RsResultPayload]:
        incoming = list(rows)
        if not incoming:
            return []

        symbols = {
            row.code: row.id
            for row in self.session.scalars(select(Symbol).where(Symbol.code.in_([item.code for item in incoming]))).all()
        }
        benchmark_id = self.session.scalar(
            select(Benchmark.id).where(Benchmark.benchmark_code == MARKET_BENCHMARKS[market])
        )
        if benchmark_id is None:
            raise KeyError(f"missing benchmark id for market {market}")

        existing = {
            (row.symbol_id, row.trade_date): row
            for row in self.session.scalars(
                select(RsScore).where(
                    RsScore.symbol_id.in_(symbols.values()),
                    RsScore.trade_date.in_([item.trade_date for item in incoming]),
                )
            ).all()
        }

        for payload in incoming:
            symbol_id = symbols[payload.code]
            key = (symbol_id, payload.trade_date)
            row = existing.get(key)
            if row is None:
                row = RsScore(
                    symbol_id=symbol_id,
                    benchmark_id=benchmark_id,
                    trade_date=payload.trade_date,
                    market=payload.market,
                    return_3m=payload.return_3m,
                    return_6m=payload.return_6m,
                    return_9m=payload.return_9m,
                    return_12m=payload.return_12m,
                    relative_return_score=payload.relative_return_score,
                    rs_percentile=payload.rs_percentile,
                    rs_rating=payload.rs_rating,
                    rank_in_market=payload.rank_in_market,
                )
                self.session.add(row)
            else:
                row.benchmark_id = benchmark_id
                row.market = payload.market
                row.return_3m = payload.return_3m
                row.return_6m = payload.return_6m
                row.return_9m = payload.return_9m
                row.return_12m = payload.return_12m
                row.relative_return_score = payload.relative_return_score
                row.rs_percentile = payload.rs_percentile
                row.rs_rating = payload.rs_rating
                row.rank_in_market = payload.rank_in_market

        self.session.flush()
        return self.list_market(market)

    def list_market(self, market: str, trade_date: date | None = None, limit: int = 100) -> list[RsResultPayload]:
        target_trade_date = trade_date or self.session.scalar(
            select(func.max(RsScore.trade_date)).where(RsScore.market == market)
        )
        if target_trade_date is None:
            return []

        rows = self.session.execute(
            select(RsScore, Symbol.code)
            .join(Symbol, Symbol.id == RsScore.symbol_id)
            .where(RsScore.market == market, RsScore.trade_date == target_trade_date)
            .order_by(RsScore.rank_in_market)
            .limit(limit)
        ).all()

        return [
            RsResultPayload(
                code=code,
                market=row.market,
                trade_date=row.trade_date,
                return_3m=row.return_3m,
                return_6m=row.return_6m,
                return_9m=row.return_9m,
                return_12m=row.return_12m,
                relative_return_score=row.relative_return_score,
                rs_percentile=row.rs_percentile,
                rs_rating=row.rs_rating,
                rank_in_market=row.rank_in_market,
            )
            for row, code in rows
        ]

    def list_market_with_prices(
        self, market: str, trade_date: date | None = None, page: int = 1, size: int = 100
    ) -> tuple[list[dict], int, date | None]:
        """시장별 RS 랭킹 조회 (종목명, 최신 가격 포함).

        Returns:
            (items, total_count, target_trade_date)
        """
        from app.models.daily_price import DailyPrice

        # RS 데이터의 최신 거래일 찾기
        target_trade_date = trade_date or self.session.scalar(
            select(func.max(RsScore.trade_date)).where(RsScore.market == market)
        )
        if target_trade_date is None:
            return [], 0, None

        # 전체 개수 조회
        total_count = self.session.scalar(
            select(func.count())
            .select_from(RsScore)
            .where(RsScore.market == market, RsScore.trade_date == target_trade_date)
        ) or 0

        # 최신 가격의 서브쿼리 (각 종목의 최신 가격)
        latest_price_subq = (
            select(
                DailyPrice.symbol_id,
                DailyPrice.close,
                DailyPrice.change_rate,
                func.row_number()
                .over(partition_by=DailyPrice.symbol_id, order_by=DailyPrice.trade_date.desc())
                .label("rn"),
            )
            .subquery()
        )

        # 메인 쿼리: RsScore + Symbol + 최신 가격 JOIN
        offset = (page - 1) * size
        rows = self.session.execute(
            select(
                RsScore,
                Symbol.code,
                Symbol.name,
                latest_price_subq.c.close,
                latest_price_subq.c.change_rate,
            )
            .join(Symbol, Symbol.id == RsScore.symbol_id)
            .outerjoin(
                latest_price_subq,
                (latest_price_subq.c.symbol_id == RsScore.symbol_id) & (latest_price_subq.c.rn == 1),
            )
            .where(RsScore.market == market, RsScore.trade_date == target_trade_date)
            .order_by(RsScore.rank_in_market)
            .limit(size)
            .offset(offset)
        ).all()

        items = [
            {
                "code": code,
                "name": name,
                "market": rs.market,
                "trade_date": rs.trade_date,
                "rs_rating": rs.rs_rating,
                "rank_in_market": rs.rank_in_market,
                "return_3m": rs.return_3m,
                "return_6m": rs.return_6m,
                "return_9m": rs.return_9m,
                "return_12m": rs.return_12m,
                "relative_return_score": rs.relative_return_score,
                "close": close if close is not None else 0,
                "change_rate": change_rate if change_rate is not None else 0,
            }
            for rs, code, name, close, change_rate in rows
        ]

        return items, total_count, target_trade_date
