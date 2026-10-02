import json
from datetime import date

import pytest

from app.core.exceptions import PriceParseError
from app.crawler.sources.naver import NaverPriceSource


def _row(code: str, day: str, close: str) -> dict[str, str]:
    return {
        "cd": code,
        "dt": day,
        "ncv": close,
        "cv": "1.25",
        "cr": "0.05",
        "ov": close,
        "hv": close,
        "lv": close,
    }


def _response(*rows: dict[str, str]) -> str:
    return json.dumps({"resultCode": "success", "result": {"siseList": list(rows)}})


class PageClient:
    def __init__(self, values: dict[str, str]):
        self.values = values
        self.calls: list[str] = []

    def get(self, url: str) -> str:
        self.calls.append(url)
        return self.values[url]


@pytest.mark.parametrize(
    ("market", "naver_code", "benchmark_code"),
    [
        ("KOSPI", "KOSPI", "KOSPI_INDEX"),
        ("KOSDAQ", "KOSDAQ", "KOSDAQ_INDEX"),
    ],
)
def test_naver_index_source_pages_json_and_maps_market(market, naver_code, benchmark_code):
    first_url = (
        "https://m.stock.naver.com/api/json/sise/dailySiseIndexListJson.nhn"
        f"?code={naver_code}&pageSize=100&page=1"
    )
    second_url = first_url[:-1] + "2"
    client = PageClient(
        {
            first_url: _response(
                _row(naver_code, "20260930", "3455.37"),
                _row(naver_code, "20260929", "3443.03"),
            ),
            second_url: _response(),
        }
    )

    rows = NaverPriceSource(client=client).fetch_benchmark_prices(market)

    assert [row.trade_date for row in rows] == [date(2026, 9, 29), date(2026, 9, 30)]
    assert all(row.market == market for row in rows)
    assert all(row.benchmark_code == benchmark_code for row in rows)
    assert client.calls == [first_url, second_url]


def test_naver_index_source_stops_at_incremental_date_boundary():
    first_url = (
        "https://m.stock.naver.com/api/json/sise/dailySiseIndexListJson.nhn"
        "?code=KOSPI&pageSize=100&page=1"
    )
    client = PageClient(
        {
            first_url: _response(
                _row("KOSPI", "20260930", "3455.37"),
                _row("KOSPI", "20260929", "3443.03"),
                _row("KOSPI", "20260928", "3430.00"),
            ),
        }
    )

    rows = NaverPriceSource(client=client).fetch_benchmark_prices(
        "KOSPI", since_date=date(2026, 9, 29)
    )

    assert [row.trade_date for row in rows] == [date(2026, 9, 30)]
    assert client.calls == [first_url]


def test_naver_index_source_does_not_treat_error_response_as_end_of_history():
    first_url = (
        "https://m.stock.naver.com/api/json/sise/dailySiseIndexListJson.nhn"
        "?code=KOSPI&pageSize=100&page=1"
    )
    client = PageClient({first_url: '{"resultCode":"fail","result":{}}'})

    with pytest.raises(PriceParseError):
        NaverPriceSource(client=client).fetch_benchmark_prices("KOSPI")


def test_naver_index_source_rejects_empty_first_page_as_incomplete_history():
    first_url = (
        "https://m.stock.naver.com/api/json/sise/dailySiseIndexListJson.nhn"
        "?code=KOSPI&pageSize=100&page=1"
    )
    client = PageClient({first_url: _response()})

    with pytest.raises(PriceParseError, match="empty first page"):
        NaverPriceSource(client=client).fetch_benchmark_prices("KOSPI")


def test_naver_index_source_rejects_history_truncated_by_page_cap():
    first_url = (
        "https://m.stock.naver.com/api/json/sise/dailySiseIndexListJson.nhn"
        "?code=KOSPI&pageSize=100&page=1"
    )
    client = PageClient(
        {first_url: _response(_row("KOSPI", "20260930", "3455.37"))}
    )

    with pytest.raises(PriceParseError, match="page limit"):
        NaverPriceSource(client=client, max_price_pages=1).fetch_benchmark_prices("KOSPI")
