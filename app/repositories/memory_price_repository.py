from collections import defaultdict
from collections.abc import Iterable
from datetime import date

from app.schemas.market_data import BenchmarkPricePayload, DailyPricePayload


class MemoryPriceRepository:
    def __init__(self) -> None:
        self._daily_prices: dict[str, list[DailyPricePayload]] = defaultdict(list)
        self._benchmark_prices: dict[str, list[BenchmarkPricePayload]] = defaultdict(list)

    def save_symbol_prices(self, code: str, prices: Iterable[DailyPricePayload]) -> list[DailyPricePayload]:
        self._daily_prices[code] = sorted(prices, key=lambda row: row.trade_date)
        return self._daily_prices[code]

    def save_benchmark_prices(
        self, benchmark_code: str, prices: Iterable[BenchmarkPricePayload]
    ) -> list[BenchmarkPricePayload]:
        self._benchmark_prices[benchmark_code] = sorted(prices, key=lambda row: row.trade_date)
        return self._benchmark_prices[benchmark_code]

    def get_symbol_prices(self, code: str) -> list[DailyPricePayload]:
        return self._daily_prices[code]

    def get_benchmark_prices(self, benchmark_code: str) -> list[BenchmarkPricePayload]:
        return self._benchmark_prices[benchmark_code]

    def get_latest_symbol_trade_date(self, code: str) -> date | None:
        rows = self._daily_prices[code]
        return rows[-1].trade_date if rows else None

    def get_latest_benchmark_trade_date(self, benchmark_code: str) -> date | None:
        rows = self._benchmark_prices[benchmark_code]
        return rows[-1].trade_date if rows else None
