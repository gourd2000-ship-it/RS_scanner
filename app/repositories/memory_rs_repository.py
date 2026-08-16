from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from app.schemas.market_data import RsResultPayload


class MemoryRsRepository:
    def __init__(self) -> None:
        self._results: dict[str, list[RsResultPayload]] = defaultdict(list)

    def save_many(self, market: str, rows: Iterable[RsResultPayload]) -> list[RsResultPayload]:
        self._results[market] = sorted(rows, key=lambda row: row.rank_in_market)
        return self._results[market]

    def list_market(self, market: str, trade_date=None, limit: int = 100) -> list[RsResultPayload]:
        return self._results[market][:limit]

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
    ) -> tuple[list[dict], int, date | None]:
        """시장별 RS 랭킹 조회 (in-memory, 테스트용)."""
        results = self._results.get(market, [])
        if not results:
            return [], 0, None

        # 최신 거래일 찾기 (첫 번째 결과의 trade_date 사용)
        target_trade_date = trade_date or (results[0].trade_date if results else None)
        if target_trade_date is None:
            return [], 0, None

        # 필터링
        filtered = results
        if min_rs is not None:
            filtered = [r for r in filtered if r.rs_rating >= min_rs]
        if max_rs is not None:
            filtered = [r for r in filtered if r.rs_rating <= max_rs]

        # 정렬
        SORT_KEY_MAP = {
            "rank_in_market": lambda r: r.rank_in_market,
            "rs_rating": lambda r: r.rs_rating,
            "rs_1m": lambda r: r.rs_1m,
            "rs_3m": lambda r: r.rs_3m,
            "rs_6m": lambda r: r.rs_6m,
            "rs_12m": lambda r: r.rs_12m,
            "return_1m": lambda r: r.return_1m,
            "return_3m": lambda r: r.return_3m,
            "return_6m": lambda r: r.return_6m,
            "return_9m": lambda r: r.return_9m,
            "return_12m": lambda r: r.return_12m,
            "relative_return_score": lambda r: r.relative_return_score,
        }
        sort_key = SORT_KEY_MAP.get(sort_by, SORT_KEY_MAP["rank_in_market"])
        reverse = (order == "desc")
        filtered = sorted(filtered, key=sort_key, reverse=reverse)

        total_count = len(filtered)

        # 페이지네이션
        offset = (page - 1) * size
        page_results = filtered[offset:offset + size]

        # dict 형식으로 변환 (더미 가격 정보 포함)
        items = [
            {
                "code": r.code,
                "name": f"종목{r.code}",  # 더미 종목명
                "market": r.market,
                "trade_date": r.trade_date,
                "rs_rating": r.rs_rating,
                "rank_in_market": r.rank_in_market,
                "return_1m": r.return_1m,
                "return_3m": r.return_3m,
                "return_6m": r.return_6m,
                "return_9m": r.return_9m,
                "return_12m": r.return_12m,
                "rs_1m": r.rs_1m,
                "rs_3m": r.rs_3m,
                "rs_6m": r.rs_6m,
                "rs_12m": r.rs_12m,
                "relative_return_score": r.relative_return_score,
                "close": Decimal("50000"),  # 더미 종가
                "change_rate": Decimal("0.5"),  # 더미 등락률
            }
            for r in page_results
        ]

        return items, total_count, target_trade_date
