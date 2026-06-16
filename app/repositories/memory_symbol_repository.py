from collections.abc import Iterable

from app.schemas.market_data import SymbolPayload
from app.schemas.response import SymbolItem


class MemorySymbolRepository:
    def __init__(self) -> None:
        self._symbols: dict[str, SymbolPayload] = {}

    def upsert_many(self, symbols: Iterable[SymbolPayload]) -> list[SymbolPayload]:
        for symbol in symbols:
            self._symbols[symbol.code] = symbol
        return list(self._symbols.values())

    def list_all(self) -> list[SymbolPayload]:
        return list(self._symbols.values())

    def list_filtered(
        self,
        market: str | None = None,
        is_active: bool | None = None,
        search: str | None = None,
        page: int = 1,
        size: int = 100,
    ) -> tuple[list[SymbolItem], int]:
        """필터링된 종목 목록 조회 (in-memory)."""
        # 모든 심볼을 SymbolItem으로 변환 (기본값으로 is_active=True 설정)
        all_items = [
            SymbolItem(
                code=s.code,
                name=s.name,
                market=s.market,
                sector=None,
                industry=None,
                is_active=True,
                listed_at=None,
            )
            for s in self._symbols.values()
        ]

        # 필터링
        filtered = all_items
        if market is not None:
            filtered = [item for item in filtered if item.market == market]
        if is_active is not None:
            filtered = [item for item in filtered if item.is_active == is_active]
        if search is not None:
            search_lower = search.lower()
            filtered = [
                item for item in filtered
                if search_lower in item.name.lower() or search_lower in item.code.lower()
            ]

        total_count = len(filtered)

        # 정렬 (market, code 순)
        filtered.sort(key=lambda x: (x.market, x.code))

        # 페이지네이션
        offset = (page - 1) * size
        items = filtered[offset:offset + size]

        return items, total_count
