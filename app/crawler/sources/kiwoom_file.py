"""Price source backed by the Hermes Agent Sam Kiwoom file bridge."""

from datetime import date

from app.core.exceptions import PriceFetchError
from app.crawler.kiwoom_file_bridge import KiwoomFileBridgeClient
from app.crawler.sources.base import PriceSource


class KiwoomFileBridgePriceSource(PriceSource):
    """Use Sam's fixed ``kiwoomcli domestic candles daily`` operation."""

    provider_name = "kiwoom_sam_file"
    adjusted_prices = True
    fetch_full_history_on_fallback = True
    reject_provider_conflicts = True

    def __init__(
        self,
        client: KiwoomFileBridgeClient | None = None,
    ) -> None:
        self.client = client or KiwoomFileBridgeClient()
        self.max_concurrency = 1

    def fetch_symbols(self):
        return []

    def fetch_benchmark_prices(self, market: str, since_date: date | None = None):
        raise PriceFetchError(
            "kiwoom file bridge does not provide benchmarks",
            url="kiwoom-file://daily_chart/benchmark",
        )

    def build_daily_price_url(self, code: str, since_date: date | None = None) -> str:
        return f"kiwoom-file://daily_chart/{code}"

    def fetch_daily_prices(self, code: str, since_date: date | None = None):
        parsed = self.client.fetch_daily_chart(code, since_date=since_date)
        rows = sorted(
            {row.trade_date: row for row in parsed}.values(),
            key=lambda row: row.trade_date,
        )
        if since_date is not None:
            rows = [row for row in rows if row.trade_date > since_date]
        return type(parsed)(
            rows,
            invalid_rows=parsed.invalid_rows,
            response_bytes=parsed.response_bytes,
            retry_count=parsed.retry_count,
        )
