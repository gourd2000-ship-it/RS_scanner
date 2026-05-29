from collections import defaultdict
from collections.abc import Iterable

from app.schemas.market_data import RsResultPayload


class MemoryRsRepository:
    def __init__(self) -> None:
        self._results: dict[str, list[RsResultPayload]] = defaultdict(list)

    def save_many(self, market: str, rows: Iterable[RsResultPayload]) -> list[RsResultPayload]:
        self._results[market] = sorted(rows, key=lambda row: row.rank_in_market)
        return self._results[market]

    def list_market(self, market: str, trade_date=None, limit: int = 100) -> list[RsResultPayload]:
        return self._results[market][:limit]
