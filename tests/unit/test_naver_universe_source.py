import json

from app.crawler.sources.naver import NaverPriceSource
from app.schemas.market_data import SymbolPayload


class PageClient:
    def __init__(self, values):
        self.values = values
        self.calls: list[str] = []

    def get(self, url: str):
        self.calls.append(url)
        value = self.values.get(url)
        if isinstance(value, Exception):
            raise value
        return value


def _individual_page(index, items, *, total=2, has_next=False):
    return json.dumps(
        {"index": str(index), "size": "2", "totalCount": str(total), "hasNext": has_next, "items": items}
    )


def _stock(code, market):
    return {"itemCode": code, "itemName": f"Name {code}", "marketType": market}


def _fund(kind):
    key = "etfItemList" if kind == "etf" else "etnItemList"
    code = "0005D0" if kind == "etf" else "530107"
    return json.dumps({"resultCode": "success", "result": {key: [{"itemcode": code, "itemname": kind}]}})


def test_naver_universe_pages_all_markets_and_validates_total_count(monkeypatch):
    monkeypatch.setattr(NaverPriceSource, "_SYMBOL_PAGE_SIZE", 2)
    base = NaverPriceSource._INDIVIDUAL_STOCKS_URL
    client = PageClient(
        {
            f"{base}?listingType=listedAtDesc&exchangeType=KRX&index=0&size=2": _individual_page(
                0,
                [_stock("000001", "KOSPI"), _stock("100001", "KOSDAQ")],
                total=3,
                has_next=True,
            ),
            f"{base}?listingType=listedAtDesc&exchangeType=KRX&index=1&size=2": _individual_page(
                1, [_stock("000002", "KOSPI")], total=3
            ),
            NaverPriceSource._ETF_API_URL: _fund("etf"),
            NaverPriceSource._ETN_API_URL: _fund("etn"),
        }
    )

    result = NaverPriceSource(client=client, max_symbol_pages=3).fetch_symbol_universe()

    assert result.complete is True
    assert result.pages_total == result.pages_succeeded == 4
    assert {symbol.code for symbol in result.symbols} == {
        "000001", "000002", "100001", "0005D0", "530107"
    }
    assert len(result.market_results["KOSPI"].symbols) == 4
    assert len(result.market_results["KOSDAQ"].symbols) == 1
    assert {symbol.symbol_type for symbol in result.symbols} == {"stock", "etf", "etn"}


def test_naver_universe_hard_page_cap_is_incomplete(monkeypatch):
    monkeypatch.setattr(NaverPriceSource, "_SYMBOL_PAGE_SIZE", 2)
    base = NaverPriceSource._INDIVIDUAL_STOCKS_URL
    client = PageClient(
        {
            f"{base}?listingType=listedAtDesc&exchangeType=KRX&index=0&size=2": _individual_page(
                0,
                [_stock("000001", "KOSPI"), _stock("100001", "KOSDAQ")],
                total=3,
                has_next=True,
            ),
            NaverPriceSource._ETF_API_URL: _fund("etf"),
            NaverPriceSource._ETN_API_URL: _fund("etn"),
        }
    )

    result = NaverPriceSource(client=client, max_symbol_pages=1).fetch_symbol_universe()

    assert result.complete is False
    assert result.error_message == "symbol_max_pages_reached:1"
    assert len(result.symbols) == 4


def test_naver_universe_keeps_partial_rows_when_page_request_fails(monkeypatch):
    monkeypatch.setattr(NaverPriceSource, "_SYMBOL_PAGE_SIZE", 2)
    base = NaverPriceSource._INDIVIDUAL_STOCKS_URL
    client = PageClient(
        {
            f"{base}?listingType=listedAtDesc&exchangeType=KRX&index=0&size=2": _individual_page(
                0,
                [_stock("000001", "KOSPI"), _stock("100001", "KOSDAQ")],
                total=3,
                has_next=True,
            ),
            f"{base}?listingType=listedAtDesc&exchangeType=KRX&index=1&size=2": RuntimeError("timeout"),
            NaverPriceSource._ETF_API_URL: _fund("etf"),
            NaverPriceSource._ETN_API_URL: _fund("etn"),
        }
    )

    result = NaverPriceSource(client=client, max_symbol_pages=3).fetch_symbol_universe()

    assert result.complete is False
    assert result.pages_total == 4
    assert result.pages_succeeded == 3
    assert result.error_message == "symbol_page_1_RuntimeError"
    assert {symbol.code for symbol in result.symbols} == {
        "000001", "100001", "0005D0", "530107"
    }


def test_naver_universe_rejects_empty_first_page(monkeypatch):
    monkeypatch.setattr(NaverPriceSource, "_SYMBOL_PAGE_SIZE", 2)
    base = NaverPriceSource._INDIVIDUAL_STOCKS_URL
    client = PageClient(
        {
            f"{base}?listingType=listedAtDesc&exchangeType=KRX&index=0&size=2": _individual_page(
                0, [], total=0
            ),
            NaverPriceSource._ETF_API_URL: _fund("etf"),
            NaverPriceSource._ETN_API_URL: _fund("etn"),
        }
    )

    result = NaverPriceSource(client=client, max_symbol_pages=1).fetch_symbol_universe()

    assert result.complete is False
    assert result.error_message == "symbol_unexpected_empty_page"
    assert all(not market.complete for market in result.market_results.values())


def test_naver_universe_does_not_accept_overlapping_pages_as_complete(monkeypatch):
    monkeypatch.setattr(NaverPriceSource, "_SYMBOL_PAGE_SIZE", 2)
    base = NaverPriceSource._INDIVIDUAL_STOCKS_URL
    client = PageClient(
        {
            f"{base}?listingType=listedAtDesc&exchangeType=KRX&index=0&size=2": _individual_page(
                0,
                [_stock("000001", "KOSPI"), _stock("100001", "KOSDAQ")],
                total=3,
                has_next=True,
            ),
            f"{base}?listingType=listedAtDesc&exchangeType=KRX&index=1&size=2": _individual_page(
                1, [_stock("100001", "KOSDAQ")], total=3
            ),
            NaverPriceSource._ETF_API_URL: _fund("etf"),
            NaverPriceSource._ETN_API_URL: _fund("etn"),
        }
    )

    result = NaverPriceSource(client=client, max_symbol_pages=3).fetch_symbol_universe()

    assert result.complete is False
    assert result.error_message == "symbol_total_count_mismatch:2!=3"
    assert result.market_results["KOSDAQ"].duplicate_count == 1


def test_naver_price_request_keeps_alphanumeric_code():
    code = "0005D0"
    client = PageClient({})
    source = NaverPriceSource(client=client)
    url = source.build_daily_price_url(code)
    client.values[url] = (
        "[['날짜', '시가', '고가', '저가', '종가', '거래량'], "
        '[\"20260811\", 100, 110, 90, 105, 1000]]'
    )

    rows = source.fetch_daily_prices(code)

    assert len(rows) == 1
    assert client.calls == [url]
