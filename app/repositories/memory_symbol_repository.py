from collections.abc import Iterable

from app.schemas.market_data import SymbolPayload


class MemorySymbolRepository:
    def __init__(self) -> None:
        self._symbols: dict[str, SymbolPayload] = {}

    def upsert_many(self, symbols: Iterable[SymbolPayload]) -> list[SymbolPayload]:
        for symbol in symbols:
            self._symbols[symbol.code] = symbol
        return list(self._symbols.values())

    def list_all(self) -> list[SymbolPayload]:
        return list(self._symbols.values())
