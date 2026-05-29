from datetime import date
from pathlib import Path

from app.crawler.parsers.benchmarks import parse_benchmark_prices
from app.crawler.parsers.prices import parse_daily_prices
from app.crawler.parsers.symbols import parse_symbols
from app.crawler.sources.base import PriceSource


class ReplayPriceSource(PriceSource):
    def __init__(self, fixture_dir: str | Path) -> None:
        self.fixture_dir = Path(fixture_dir)

    def fetch_symbols(self):
        kospi = parse_symbols((self.fixture_dir / "symbols_kospi.html").read_text(encoding="utf-8"), market="KOSPI")
        kosdaq = parse_symbols((self.fixture_dir / "symbols_kosdaq.html").read_text(encoding="utf-8"), market="KOSDAQ")
        return kospi + kosdaq

    def fetch_daily_prices(self, code: str, since_date: date | None = None):
        rows = parse_daily_prices((self.fixture_dir / f"prices_{code}.html").read_text(encoding="utf-8"))
        if since_date is None:
            return rows
        return [row for row in rows if row.trade_date > since_date]

    def fetch_benchmark_prices(self, market: str, since_date: date | None = None):
        benchmark_code = "KOSPI_INDEX" if market == "KOSPI" else "KOSDAQ_INDEX"
        rows = parse_benchmark_prices(
            (self.fixture_dir / f"benchmark_{market.lower()}.html").read_text(encoding="utf-8"),
            market=market,
            benchmark_code=benchmark_code,
        )
        if since_date is None:
            return rows
        return [row for row in rows if row.trade_date > since_date]
