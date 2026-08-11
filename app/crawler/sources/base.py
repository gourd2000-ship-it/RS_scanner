from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from app.schemas.market_data import BenchmarkPricePayload, DailyPricePayload, SymbolPayload


@dataclass(frozen=True)
class UniverseMarketFetchResult:
    """페이지 단위 universe 수집 결과."""

    market: str
    symbols: list[SymbolPayload]
    pages_total: int = 1
    pages_succeeded: int = 1
    complete: bool = True
    duplicate_count: int = 0
    invalid_count: int = 0
    termination_reason: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class SymbolUniverseFetchResult:
    """종목 목록과 페이지 단위 수집 완전성 메타데이터."""

    symbols: list[SymbolPayload]
    pages_total: int = 1
    pages_succeeded: int = 1
    complete: bool = True
    error_message: str | None = None
    market_results: dict[str, UniverseMarketFetchResult] = field(default_factory=dict)


class PriceSource(Protocol):
    def fetch_symbols(self) -> list[SymbolPayload]: ...

    def fetch_daily_prices(self, code: str, since_date: date | None = None) -> list[DailyPricePayload]: ...

    def fetch_benchmark_prices(
        self, market: str, since_date: date | None = None
    ) -> list[BenchmarkPricePayload]: ...
