from datetime import date, timedelta

from app.core.exceptions import PriceFetchError, PriceParseError
from app.crawler.client import NaverHttpClient
from app.crawler.parsers.benchmarks import parse_benchmark_prices
from app.crawler.parsers.fchart import ParsedPriceRows, parse_fchart_prices
from app.crawler.parsers.prices import parse_daily_prices
from app.crawler.parsers.symbols import parse_symbols
from app.crawler.sources.base import (
    PriceSource,
    SymbolUniverseFetchResult,
    UniverseMarketFetchResult,
)


class NaverPriceSource(PriceSource):
    def __init__(self, client: NaverHttpClient | None = None, max_symbol_pages: int = 40, max_price_pages: int = 80) -> None:
        self.client = client or NaverHttpClient()
        self.max_symbol_pages = max_symbol_pages
        self.max_price_pages = max_price_pages
        self.max_concurrency = getattr(self.client, "max_concurrency", 1)

    _ETF_API_URL = "https://finance.naver.com/api/sise/etfItemList.naver"

    def fetch_symbols(self):
        return self.fetch_symbol_universe().symbols

    def fetch_symbol_universe(self) -> SymbolUniverseFetchResult:
        """시장별 페이지 결과와 중간 실패 여부를 함께 반환한다."""
        market_results = [
            self._fetch_market_symbols_with_stats("KOSPI", sosok=0),
            self._fetch_market_symbols_with_stats("KOSDAQ", sosok=1),
        ]
        errors = [result.error_message for result in market_results if result.error_message]
        return SymbolUniverseFetchResult(
            symbols=[
                symbol
                for result in market_results
                for symbol in result.symbols
            ],
            pages_total=sum(result.pages_total for result in market_results),
            pages_succeeded=sum(result.pages_succeeded for result in market_results),
            complete=all(result.complete for result in market_results),
            error_message=";".join(errors) if errors else None,
            market_results={result.market: result for result in market_results},
        )

    def fetch_etf_codes(self) -> set[str]:
        """Naver ETF JSON API에서 ETF 종목 코드 set을 반환. 실패 시 빈 set."""
        from app.crawler.parsers.symbols import parse_etf_codes
        try:
            json_text = self.client.get(self._ETF_API_URL)
            return parse_etf_codes(json_text)
        except Exception:
            return set()

    _FCHART_URL = "https://fchart.stock.naver.com/siseJson.naver"

    def build_daily_price_url(self, code: str, since_date: date | None = None) -> str:
        """가격 요청 URL을 동일한 규칙으로 생성한다."""
        if since_date is not None:
            start_date = since_date + timedelta(days=1)
        else:
            start_date = date.today() - timedelta(days=730)

        end_date = date.today()
        return (
            f"{self._FCHART_URL}"
            f"?symbol={code}"
            f"&requestType=1"
            f"&startTime={start_date.strftime('%Y%m%d')}"
            f"&endTime={end_date.strftime('%Y%m%d')}"
            f"&timeframe=day"
        )

    def fetch_daily_prices(self, code: str, since_date: date | None = None):
        """수정주가 기반 일봉 데이터 조회 (fchart API)."""
        if since_date is not None and since_date + timedelta(days=1) > date.today():
            return []

        url = self.build_daily_price_url(code, since_date)
        try:
            raw_text = self.client.get(url)
        except Exception as exc:  # noqa: BLE001
            response = getattr(exc, "response", None)
            raise PriceFetchError(
                "fchart request failed",
                url=url,
                http_status=getattr(response, "status_code", None),
                retry_count=getattr(exc, "retry_count", 0),
                response_bytes=len(getattr(response, "content", b"") or b""),
            ) from exc

        try:
            rows = parse_fchart_prices(raw_text)
        except PriceParseError as exc:
            raise PriceParseError(
                str(exc),
                url=url,
                invalid_rows=exc.invalid_rows,
                response_bytes=exc.response_bytes,
            ) from exc

        if since_date is not None:
            rows = ParsedPriceRows(
                [r for r in rows if r.trade_date > since_date],
                invalid_rows=rows.invalid_rows,
                response_bytes=rows.response_bytes,
            )

        return ParsedPriceRows(
            sorted(rows, key=lambda r: r.trade_date),
            invalid_rows=rows.invalid_rows,
            response_bytes=rows.response_bytes,
        )

    # Naver Finance URL 코드와 내부 benchmark_code 매핑
    _NAVER_INDEX_CODES = {"KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ"}
    _INTERNAL_BENCHMARK_CODES = {"KOSPI": "KOSPI_INDEX", "KOSDAQ": "KOSDAQ_INDEX"}

    def fetch_benchmark_prices(self, market: str, since_date: date | None = None):
        naver_code = self._NAVER_INDEX_CODES[market]
        internal_code = self._INTERNAL_BENCHMARK_CODES[market]
        rows: list = []
        seen_dates: set[date] = set()
        for page in range(1, self.max_price_pages + 1):
            html = self.client.get(f"https://finance.naver.com/sise/sise_index_day.naver?code={naver_code}&page={page}")
            parsed = parse_benchmark_prices(html, market=market, benchmark_code=internal_code)
            if not parsed:
                break

            should_stop = False
            for row in parsed:
                if since_date is not None and row.trade_date <= since_date:
                    should_stop = True
                    break  # 날짜가 내림차순이므로 즉시 중단
                if row.trade_date in seen_dates:
                    continue
                seen_dates.add(row.trade_date)
                rows.append(row)

            if should_stop:
                break

        return sorted(rows, key=lambda row: row.trade_date)

    def _fetch_market_symbols(self, market: str, *, sosok: int):
        return self._fetch_market_symbols_with_stats(market, sosok=sosok).symbols

    def _fetch_market_symbols_with_stats(
        self,
        market: str,
        *,
        sosok: int,
    ) -> UniverseMarketFetchResult:
        seen_codes: set[str] = set()
        rows: list = []
        pages_total = 0
        pages_succeeded = 0
        duplicate_count = 0
        for page in range(1, self.max_symbol_pages + 1):
            pages_total += 1
            try:
                html = self.client.get(
                    f"https://finance.naver.com/sise/sise_market_sum.naver"
                    f"?sosok={sosok}&page={page}"
                )
                parsed = parse_symbols(html, market=market)
            except Exception as exc:  # noqa: BLE001
                return UniverseMarketFetchResult(
                    market=market,
                    symbols=rows,
                    pages_total=pages_total,
                    pages_succeeded=pages_succeeded,
                    complete=False,
                    duplicate_count=duplicate_count,
                    termination_reason="request_error",
                    error_message=f"{market}:symbol_page_{type(exc).__name__}",
                )
            pages_succeeded += 1
            if not parsed:
                return UniverseMarketFetchResult(
                    market=market,
                    symbols=rows,
                    pages_total=pages_total,
                    pages_succeeded=pages_succeeded,
                    complete=True,
                    duplicate_count=duplicate_count,
                    termination_reason="empty_page",
                )

            new_items = [row for row in parsed if row.code not in seen_codes]
            duplicate_count += len(parsed) - len(new_items)
            if not new_items:
                return UniverseMarketFetchResult(
                    market=market,
                    symbols=rows,
                    pages_total=pages_total,
                    pages_succeeded=pages_succeeded,
                    complete=True,
                    duplicate_count=duplicate_count,
                    termination_reason="repeated_page",
                )

            for row in new_items:
                seen_codes.add(row.code)
            rows.extend(new_items)

        return UniverseMarketFetchResult(
            market=market,
            symbols=rows,
            pages_total=pages_total,
            pages_succeeded=pages_succeeded,
            complete=False,
            duplicate_count=duplicate_count,
            termination_reason="max_pages_reached",
            error_message=f"{market}:max_symbol_pages_reached",
        )
