import logging
import re
from datetime import date, timedelta

from app.core.config import get_settings
from app.core.exceptions import PriceFetchError, PriceParseError
from app.crawler.client import NaverHttpClient
from app.crawler.parsers.benchmarks import parse_naver_index_prices
from app.crawler.parsers.fchart import ParsedPriceRows, parse_fchart_prices
from app.crawler.parsers.prices import parse_daily_prices
from app.crawler.parsers.symbols import (
    parse_naver_fund_symbols,
    parse_naver_individual_stock_page,
)
from app.crawler.sources.base import (
    PriceSource,
    SymbolUniverseFetchResult,
    UniverseMarketFetchResult,
)

logger = logging.getLogger(__name__)


class NaverPriceSource(PriceSource):
    provider_name = "naver"
    _SYMBOL_CODE_PATTERN = re.compile(r"[0-9A-Za-z]{6}")
    _SYMBOL_PAGE_SIZE = 100

    def __init__(
        self,
        client: NaverHttpClient | None = None,
        max_symbol_pages: int | None = None,
        max_price_pages: int = 80,
    ) -> None:
        self.client = client or NaverHttpClient()
        self.max_symbol_pages = (
            max_symbol_pages
            if max_symbol_pages is not None
            else get_settings().naver_max_symbol_pages
        )
        self.max_price_pages = max_price_pages
        self.max_concurrency = getattr(self.client, "max_concurrency", 1)

    _ETF_API_URL = "https://finance.naver.com/api/sise/etfItemList.naver"
    _ETN_API_URL = "https://finance.naver.com/api/sise/etnItemList.naver"
    _INDIVIDUAL_STOCKS_URL = "https://stock.naver.com/api/stockSecurity/individual-stocks/v2/domestic"

    def fetch_symbols(self):
        return self.fetch_symbol_universe().symbols

    @classmethod
    def is_valid_symbol_code(cls, code: str) -> bool:
        """Naver universe가 제공하는 종목 식별자 형식을 검증한다."""
        return bool(cls._SYMBOL_CODE_PATTERN.fullmatch(code))

    def fetch_symbol_universe(self) -> SymbolUniverseFetchResult:
        """Read the current Naver stock-list API and verify its total-count contract."""
        rows_by_market: dict[str, list] = {"KOSPI": [], "KOSDAQ": []}
        seen_codes: set[str] = set()
        duplicates_by_market = {"KOSPI": 0, "KOSDAQ": 0}
        pages_total = 0
        pages_succeeded = 0
        expected_total: int | None = None
        error_message: str | None = None
        termination_reason = "max_pages_reached"
        reached_end = False

        for page in range(self.max_symbol_pages):
            pages_total += 1
            url = (
                f"{self._INDIVIDUAL_STOCKS_URL}?listingType=listedAtDesc&exchangeType=KRX"
                f"&index={page}&size={self._SYMBOL_PAGE_SIZE}"
            )
            try:
                payload = self.client.get(url)
                parsed, total_count, has_next = parse_naver_individual_stock_page(
                    payload,
                    expected_index=page,
                )
            except Exception as exc:  # noqa: BLE001
                error_message = f"symbol_page_{page}_{type(exc).__name__}"
                termination_reason = "request_error"
                break
            pages_succeeded += 1
            if expected_total is None:
                expected_total = total_count
            elif total_count != expected_total:
                error_message = "symbol_total_count_changed"
                termination_reason = "total_count_changed"
                break

            if not parsed:
                error_message = "symbol_unexpected_empty_page"
                termination_reason = "empty_page"
                break

            page_codes: set[str] = set()
            for symbol in parsed:
                if symbol.code in page_codes or symbol.code in seen_codes:
                    duplicates_by_market[symbol.market] += 1
                    continue
                page_codes.add(symbol.code)
                seen_codes.add(symbol.code)
                rows_by_market[symbol.market].append(symbol)

            if has_next is False:
                reached_end = True
                termination_reason = "end_of_list"
                break
        else:
            error_message = f"symbol_max_pages_reached:{self.max_symbol_pages}"

        actual_stock_total = sum(map(len, rows_by_market.values()))
        if expected_total is not None and actual_stock_total != expected_total and error_message is None:
            error_message = f"symbol_total_count_mismatch:{actual_stock_total}!={expected_total}"
            termination_reason = "total_count_mismatch"

        for symbol_type, url, list_key in (
            ("etf", self._ETF_API_URL, "etfItemList"),
            ("etn", self._ETN_API_URL, "etnItemList"),
        ):
            pages_total += 1
            try:
                fund_symbols = parse_naver_fund_symbols(
                    self.client.get(url),
                    list_key=list_key,
                    symbol_type=symbol_type,
                )
                pages_succeeded += 1
            except Exception as exc:  # noqa: BLE001
                fund_symbols = []
                feed_error = f"{symbol_type}_list_{type(exc).__name__}"
                error_message = ";".join(filter(None, (error_message, feed_error)))
                termination_reason = "fund_list_error"
            for symbol in fund_symbols:
                if symbol.code in seen_codes:
                    duplicates_by_market["KOSPI"] += 1
                    continue
                seen_codes.add(symbol.code)
                rows_by_market["KOSPI"].append(symbol)

        if any(duplicates_by_market.values()) and error_message is None:
            error_message = "symbol_page_overlap"
            termination_reason = "page_overlap"
        complete = reached_end and expected_total == actual_stock_total and error_message is None
        market_results = {
            market: UniverseMarketFetchResult(
                market=market,
                symbols=rows_by_market[market],
                pages_total=pages_total,
                pages_succeeded=pages_succeeded,
                complete=complete,
                duplicate_count=duplicates_by_market[market],
                termination_reason=termination_reason,
                error_message=error_message,
            )
            for market in ("KOSPI", "KOSDAQ")
        }
        return SymbolUniverseFetchResult(
            symbols=rows_by_market["KOSPI"] + rows_by_market["KOSDAQ"],
            pages_total=pages_total,
            pages_succeeded=pages_succeeded,
            complete=complete,
            error_message=error_message,
            market_results=market_results,
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
    _INDEX_HISTORY_URL = "https://m.stock.naver.com/api/json/sise/dailySiseIndexListJson.nhn"

    def fetch_benchmark_prices(self, market: str, since_date: date | None = None):
        naver_code = self._NAVER_INDEX_CODES[market]
        internal_code = self._INTERNAL_BENCHMARK_CODES[market]
        rows: list = []
        seen_dates: set[date] = set()
        for page in range(1, self.max_price_pages + 1):
            url = f"{self._INDEX_HISTORY_URL}?code={naver_code}&pageSize=100&page={page}"
            payload = self.client.get(url)
            parsed = parse_naver_index_prices(
                payload,
                market=market,
                benchmark_code=internal_code,
                expected_naver_code=naver_code,
            )
            if not parsed:
                if page == 1:
                    raise PriceParseError("Naver index history returned an empty first page")
                break

            page_dates = [row.trade_date for row in parsed]
            if any(left <= right for left, right in zip(page_dates, page_dates[1:])):
                raise PriceParseError("Naver index page is not strictly newest-first")
            new_dates = set(page_dates) - seen_dates
            if not new_dates:
                raise PriceParseError("Naver index history repeated a page without progress")

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
                return sorted(rows, key=lambda row: row.trade_date)
        else:
            raise PriceParseError(
                f"Naver index history exceeded the configured page limit ({self.max_price_pages})"
            )

        return sorted(rows, key=lambda row: row.trade_date)
