from datetime import date
from typing import Protocol

from app.schemas.market_data import BenchmarkPricePayload, DailyPricePayload, SymbolPayload


class PriceSource(Protocol):
    def fetch_symbols(self) -> list[SymbolPayload]: ...

    def fetch_daily_prices(self, code: str, since_date: date | None = None) -> list[DailyPricePayload]: ...

    def fetch_benchmark_prices(
        self, market: str, since_date: date | None = None
    ) -> list[BenchmarkPricePayload]: ...
