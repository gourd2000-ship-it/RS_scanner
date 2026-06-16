from datetime import date

from app.crawler.client import NaverHttpClient
from app.crawler.parsers.benchmarks import parse_benchmark_prices
from app.crawler.parsers.prices import parse_daily_prices
from app.crawler.parsers.symbols import parse_symbols
from app.crawler.sources.base import PriceSource


class NaverPriceSource(PriceSource):
    def __init__(self, client: NaverHttpClient | None = None, max_symbol_pages: int = 40, max_price_pages: int = 80) -> None:
        self.client = client or NaverHttpClient()
        self.max_symbol_pages = max_symbol_pages
        self.max_price_pages = max_price_pages

    _ETF_API_URL = "https://finance.naver.com/api/sise/etfItemList.naver"

    def fetch_symbols(self):
        kospi = self._fetch_market_symbols("KOSPI", sosok=0)
        kosdaq = self._fetch_market_symbols("KOSDAQ", sosok=1)
        return kospi + kosdaq

    def fetch_etf_codes(self) -> set[str]:
        """Naver ETF JSON API에서 ETF 종목 코드 set을 반환. 실패 시 빈 set."""
        from app.crawler.parsers.symbols import parse_etf_codes
        try:
            json_text = self.client.get(self._ETF_API_URL)
            return parse_etf_codes(json_text)
        except Exception:
            return set()

    def fetch_daily_prices(self, code: str, since_date: date | None = None):
        rows: list = []
        seen_dates: set[date] = set()
        for page in range(1, self.max_price_pages + 1):
            html = self.client.get(f"https://finance.naver.com/item/sise_day.naver?code={code}&page={page}")
            parsed = parse_daily_prices(html)
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
        seen_codes: set[str] = set()
        rows = []
        for page in range(1, self.max_symbol_pages + 1):
            html = self.client.get(f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}")
            parsed = parse_symbols(html, market=market)
            if not parsed:
                break

            new_items = [row for row in parsed if row.code not in seen_codes]
            if not new_items:
                break

            for row in new_items:
                seen_codes.add(row.code)
            rows.extend(new_items)

        return rows
