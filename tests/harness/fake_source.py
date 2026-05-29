from datetime import date

from app.crawler.sources.base import PriceSource
from app.schemas.market_data import BenchmarkPricePayload, DailyPricePayload, SymbolPayload


class FakePriceSource(PriceSource):
    def __init__(
        self,
        *,
        symbols: list[SymbolPayload],
        prices_by_code: dict[str, list[DailyPricePayload]],
        benchmark_prices_by_market: dict[str, list[BenchmarkPricePayload]],
    ) -> None:
        self.symbols = symbols
        self.prices_by_code = prices_by_code
        self.benchmark_prices_by_market = benchmark_prices_by_market

    def fetch_symbols(self) -> list[SymbolPayload]:
        return self.symbols

    def fetch_daily_prices(self, code: str, since_date: date | None = None) -> list[DailyPricePayload]:
        rows = self.prices_by_code[code]
        if since_date is None:
            return rows
        return [row for row in rows if row.trade_date > since_date]

    def fetch_benchmark_prices(self, market: str, since_date: date | None = None) -> list[BenchmarkPricePayload]:
        rows = self.benchmark_prices_by_market[market]
        if since_date is None:
            return rows
        return [row for row in rows if row.trade_date > since_date]
