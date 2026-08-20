"""Kiwoom REST API source used only for targeted price fallback."""

from datetime import date
from urllib.parse import urlencode

from app.core.exceptions import PriceFetchError
from app.crawler.kiwoom_client import KiwoomRestClient
from app.crawler.parsers.kiwoom import parse_kiwoom_daily_prices
from app.crawler.sources.base import PriceSource


class KiwoomRestPriceSource(PriceSource):
    """Read-only daily-price source backed by Kiwoom ``ka10081``.

    The fallback intentionally fetches complete chart history for a target.
    This lets the caller compare overlapping dates with the persisted Naver
    observation before allowing the fallback to replace the final result.
    """

    provider_name = "kiwoom_rest"
    adjusted_prices = True
    fetch_full_history_on_fallback = True
    reject_provider_conflicts = True

    def __init__(
        self,
        client: KiwoomRestClient | None = None,
        *,
        max_continuations: int | None = None,
    ) -> None:
        self.client = client or KiwoomRestClient()
        configured_max = getattr(self.client.settings, "kiwoom_max_continuations", 20)
        self.max_continuations = max_continuations or configured_max
        self.max_concurrency = getattr(self.client, "max_concurrency", 1)

    def fetch_symbols(self):
        """Kiwoom is not the universe provider in this design."""
        return []

    def fetch_benchmark_prices(self, market: str, since_date: date | None = None):
        raise PriceFetchError(
            "kiwoom fallback source does not provide benchmarks",
            url="kiwoom://chart/benchmark",
        )

    def build_daily_price_url(self, code: str, since_date: date | None = None) -> str:
        query = urlencode(
            {
                "api-id": "ka10081",
                "stk_cd": code,
                "base_dt": "00000000",
                "upd_stkpc_tp": getattr(
                    self.client.settings,
                    "kiwoom_adjusted_price_type",
                    "1",
                ),
            }
        )
        return f"{self.client.chart_url}?{query}"

    def fetch_daily_prices(
        self,
        code: str,
        since_date: date | None = None,
    ):
        all_rows = []
        invalid_rows = 0
        response_bytes = 0
        retry_count = 0
        continuation = False
        next_key: str | None = None

        for page in range(self.max_continuations):
            response = self.client.fetch_daily_chart_page(
                code,
                base_date="00000000",
                continuation=continuation,
                next_key=next_key,
            )
            parsed = parse_kiwoom_daily_prices(
                response.payload,
                response_bytes=response.response_bytes,
            )
            all_rows.extend(parsed)
            invalid_rows += parsed.invalid_rows
            response_bytes += parsed.response_bytes or 0
            retry_count += response.retry_count
            if not response.continuation or not response.next_key:
                break
            continuation = True
            next_key = response.next_key
        else:
            raise PriceFetchError(
                "kiwoom daily chart continuation limit exceeded",
                url=self.build_daily_price_url(code, since_date),
                response_bytes=response_bytes,
            )

        by_date = {row.trade_date: row for row in all_rows}
        rows = sorted(by_date.values(), key=lambda row: row.trade_date)
        if since_date is not None:
            rows = [row for row in rows if row.trade_date > since_date]

        # Reuse ParsedPriceRows so sync_prices can preserve provider response
        # size and partial-parser information in crawl_target_results.
        result = type(parsed)(
            rows,
            invalid_rows=invalid_rows,
            response_bytes=response_bytes,
            retry_count=retry_count,
        )
        return result


def create_kiwoom_fallback_source(settings=None) -> PriceSource:
    """Build the configured Kiwoom fallback transport."""
    from app.core.config import get_settings

    configured_settings = settings or get_settings()
    transport = str(
        getattr(configured_settings, "kiwoom_fallback_transport", "rest")
    ).strip().lower()
    if transport in {"file", "sam", "sam_file", "file_bridge"}:
        from app.crawler.sources.kiwoom_file import KiwoomFileBridgePriceSource
        from app.crawler.kiwoom_file_bridge import KiwoomFileBridgeClient

        return KiwoomFileBridgePriceSource(
            KiwoomFileBridgeClient(settings=configured_settings)
        )
    if transport == "rest":
        return KiwoomRestPriceSource(KiwoomRestClient(settings=configured_settings))
    raise ValueError(f"unsupported Kiwoom fallback transport: {transport}")
