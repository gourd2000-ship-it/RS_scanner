from collections.abc import Iterable
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.benchmark import Benchmark
from app.models.rs_score import RsScore
from app.models.symbol import Symbol
from app.schemas.market_data import RsResultPayload
from app.services.rs.policy import MARKET_BENCHMARKS


class RsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_many(
        self,
        market: str,
        rows: Iterable[RsResultPayload],
        *,
        rs_run_id: int | None = None,
    ) -> list[RsResultPayload]:
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
                    return_1m=payload.return_1m,
                    return_3m=payload.return_3m,
                    return_6m=payload.return_6m,
                    return_9m=payload.return_9m,
                    return_12m=payload.return_12m,
                    relative_return_score=payload.relative_return_score,
                    rs_percentile=payload.rs_percentile,
                    rs_rating=payload.rs_rating,
                    rank_in_market=payload.rank_in_market,
                    rs_run_id=rs_run_id,
                )
                self.session.add(row)
            else:
                row.benchmark_id = benchmark_id
                row.market = payload.market
                row.return_1m = payload.return_1m
                row.return_3m = payload.return_3m
                row.return_6m = payload.return_6m
                row.return_9m = payload.return_9m
                row.return_12m = payload.return_12m
                row.relative_return_score = payload.relative_return_score
                row.rs_percentile = payload.rs_percentile
                row.rs_rating = payload.rs_rating
                row.rank_in_market = payload.rank_in_market
                row.rs_run_id = rs_run_id

        self.session.flush()
        return incoming

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
                return_1m=row.return_1m,
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

    # 섹터별 종목명 키워드 매핑
    _SECTOR_KEYWORDS: dict[str, list[str]] = {
        "semiconductor": ["%반도체%", "%웨이퍼%", "%파운드리%", "%팹리스%"],
        "auto": ["%자동차%", "%모빌리티%"],
        "energy": ["%전력%", "%에너지%", "%태양광%", "%풍력%", "%원전%"],
        "machinery": ["%기계%", "%장비%"],
        "battery": ["%2차전지%", "%배터리%", "%리튬%"],
        "infra": ["%건설%", "%시공%", "%인프라%"],
        "consumer": ["%유통%", "%식품%", "%의류%", "%패션%"],
        "finance": ["%금융%", "%은행%", "%증권%", "%보험%", "%카드%", "%저축%"],
        "it": ["%소프트웨어%", "%클라우드%", "%플랫폼%"],
        "defense": ["%방산%", "%항공%", "%방위%"],
        "chemicals": ["%화학%", "%소재%", "%섬유%"],
        "shipping": ["%조선%", "%해운%", "%물류%", "%항만%"],
        "bio": ["%바이오%", "%제약%", "%의료%", "%헬스%", "%생명%"],
    }

    def list_market_with_prices(
        self,
        market: str,
        trade_date: date | None = None,
        page: int = 1,
        size: int = 100,
        min_rs: int | None = None,
        max_rs: int | None = None,
        sort_by: str = "rank_in_market",
        order: str = "asc",
        exclude_etf: bool = False,
        sector: str | None = None,
        search: str | None = None,
    ) -> tuple[list[dict], int, date | None]:
        """시장별 RS 랭킹 조회 (종목명, 최신 가격 포함).

        Args:
            market: 시장 구분 (KOSPI/KOSDAQ)
            trade_date: 기준일 (None이면 최신 거래일)
            page: 페이지 번호 (1부터 시작)
            size: 페이지 크기
            min_rs: 최소 RS Rating (1~99)
            max_rs: 최대 RS Rating (1~99)
            sort_by: 정렬 기준 컬럼명
            order: 정렬 순서 (asc/desc)

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

        # 필터 조건 구성
        filters = [RsScore.market == market, RsScore.trade_date == target_trade_date]
        if min_rs is not None:
            filters.append(RsScore.rs_rating >= min_rs)
        if max_rs is not None:
            filters.append(RsScore.rs_rating <= max_rs)
        if exclude_etf:
            filters.append(Symbol.symbol_type == "stock")
        if sector and sector != "all":
            keywords = self._SECTOR_KEYWORDS.get(sector, [])
            if keywords:
                filters.append(or_(*[Symbol.name.ilike(kw) for kw in keywords]))
        if search:
            search_pattern = f"%{search}%"
            filters.append(
                (Symbol.name.ilike(search_pattern)) | (Symbol.code.ilike(search_pattern))
            )

        # 전체 개수 조회 (Symbol 필터가 있을 경우 JOIN 필요)
        count_q = select(func.count()).select_from(RsScore).join(Symbol, Symbol.id == RsScore.symbol_id).where(*filters)
        total_count = self.session.scalar(count_q) or 0

        # 최신 가격 서브쿼리: 종목별 최근 2일만 추출해서 등락률 계산
        ranked = (
            select(
                DailyPrice.symbol_id,
                DailyPrice.close,
                func.row_number()
                .over(partition_by=DailyPrice.symbol_id, order_by=DailyPrice.trade_date.desc())
                .label("rn"),
            )
            .where(DailyPrice.trade_date >= func.current_date() - 5)
            .subquery()
        )
        latest = select(ranked.c.symbol_id, ranked.c.close).where(ranked.c.rn == 1).subquery()
        prev = select(ranked.c.symbol_id, ranked.c.close.label("prev_close")).where(ranked.c.rn == 2).subquery()

        latest_price_subq = (
            select(
                latest.c.symbol_id,
                latest.c.close,
                (
                    (latest.c.close - prev.c.prev_close)
                    / func.nullif(prev.c.prev_close, 0)
                    * 100
                ).label("change_rate"),
            )
            .outerjoin(prev, prev.c.symbol_id == latest.c.symbol_id)
            .subquery()
        )

        # 정렬 컬럼 매핑 (SQL injection 방지)
        SORT_COLUMN_MAP = {
            "rank_in_market": RsScore.rank_in_market,
            "rs_rating": RsScore.rs_rating,
            "return_1m": RsScore.return_1m,
            "return_3m": RsScore.return_3m,
            "return_6m": RsScore.return_6m,
            "return_9m": RsScore.return_9m,
            "return_12m": RsScore.return_12m,
            "relative_return_score": RsScore.relative_return_score,
        }
        sort_column = SORT_COLUMN_MAP.get(sort_by, RsScore.rank_in_market)
        order_by_clause = sort_column.desc() if order == "desc" else sort_column.asc()

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
                latest_price_subq.c.symbol_id == RsScore.symbol_id,
            )
            .where(*filters)
            .order_by(order_by_clause)
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
                "return_1m": rs.return_1m,
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
