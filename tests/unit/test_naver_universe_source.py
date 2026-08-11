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


def test_naver_universe_reports_market_page_progress(monkeypatch):
    def fake_parse(raw, market):
        if raw == "":
            return []
        return [SymbolPayload(code=raw, name=f"Name {raw}", market=market)]

    monkeypatch.setattr("app.crawler.sources.naver.parse_symbols", fake_parse)
    client = PageClient(
        {
            "https://finance.naver.com/sise/sise_market_sum.naver?sosok=0&page=1": "KOSPI-1",
            "https://finance.naver.com/sise/sise_market_sum.naver?sosok=0&page=2": "",
            "https://finance.naver.com/sise/sise_market_sum.naver?sosok=1&page=1": "KOSDAQ-1",
            "https://finance.naver.com/sise/sise_market_sum.naver?sosok=1&page=2": "",
        }
    )

    result = NaverPriceSource(client=client, max_symbol_pages=3).fetch_symbol_universe()

    assert result.complete is True
    assert result.pages_total == 4
    assert result.pages_succeeded == 4
    assert [symbol.code for symbol in result.symbols] == ["KOSPI-1", "KOSDAQ-1"]


def test_naver_universe_preserves_partial_rows_when_a_market_page_fails(monkeypatch):
    def fake_parse(raw, market):
        if raw == "":
            return []
        return [SymbolPayload(code=raw, name=f"Name {raw}", market=market)]

    monkeypatch.setattr("app.crawler.sources.naver.parse_symbols", fake_parse)
    client = PageClient(
        {
            "https://finance.naver.com/sise/sise_market_sum.naver?sosok=0&page=1": "KOSPI-1",
            "https://finance.naver.com/sise/sise_market_sum.naver?sosok=0&page=2": RuntimeError("timeout"),
            "https://finance.naver.com/sise/sise_market_sum.naver?sosok=1&page=1": "KOSDAQ-1",
            "https://finance.naver.com/sise/sise_market_sum.naver?sosok=1&page=2": "",
        }
    )

    result = NaverPriceSource(client=client, max_symbol_pages=3).fetch_symbol_universe()

    assert result.complete is False
    assert result.pages_total == 4
    assert result.pages_succeeded == 3
    assert result.error_message == "KOSPI:symbol_page_RuntimeError"
    assert [symbol.code for symbol in result.symbols] == ["KOSPI-1", "KOSDAQ-1"]
