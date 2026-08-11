from collections.abc import Iterable

from app.schemas.market_data import SymbolPayload
from app.schemas.response import SymbolItem


class MemorySymbolRepository:
    def __init__(self) -> None:
        self._symbols: dict[str, SymbolPayload] = {}
        self._active_codes: set[str] = set()
        self._last_seen_at: dict[str, object] = {}
        self._last_snapshot_id: dict[str, int | None] = {}

    def upsert_many(
        self,
        symbols: Iterable[SymbolPayload],
        *,
        snapshot_id: int | None = None,
        seen_at: object | None = None,
    ) -> list[SymbolPayload]:
        for symbol in symbols:
            self._symbols[symbol.code] = symbol
            self._active_codes.add(symbol.code)
            if snapshot_id is not None:
                self._last_seen_at[symbol.code] = seen_at
                self._last_snapshot_id[symbol.code] = snapshot_id
        return list(self._symbols.values())

    def list_all(self) -> list[SymbolPayload]:
        return list(self._symbols.values())

    def list_price_targets(self) -> list[SymbolPayload]:
        return [
            s
            for s in self._symbols.values()
            if s.code in self._active_codes and s.symbol_type == "stock"
        ]

    def reconcile_missing(self, incoming_codes: set[str], **_: object) -> list[str]:
        missing_codes = sorted(self._active_codes - incoming_codes)
        self._active_codes.difference_update(missing_codes)
        return missing_codes

    def list_stocks_only(self) -> list[SymbolPayload]:
        return self.list_price_targets()

    def get_by_code(self, code: str) -> SymbolPayload | None:
        return self._symbols.get(code)

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
                is_active=s.code in self._active_codes,
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
