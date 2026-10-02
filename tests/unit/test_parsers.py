from datetime import date
from pathlib import Path
from decimal import Decimal
import json

import pytest

from app.core.exceptions import PriceParseError
from app.crawler.parsers.benchmarks import parse_benchmark_prices, parse_naver_index_prices
from app.crawler.parsers.prices import parse_daily_prices
from app.crawler.parsers.symbols import (
    parse_etf_codes,
    parse_naver_fund_symbols,
    parse_naver_individual_stock_page,
    parse_symbols,
)


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "naver"


def test_parse_symbols_deduplicates_and_keeps_market():
    html = (FIXTURE_DIR / "symbols_kospi.html").read_text(encoding="utf-8")

    result = parse_symbols(html, market="KOSPI")

    assert len(result) == 2
    assert {row.code for row in result} == {"005930", "000660"}
    assert all(row.market == "KOSPI" for row in result)


def test_parse_symbols_preserves_alphanumeric_naver_codes():
    html = """
    <table>
      <tr><td><a href="/item/main.naver?code=0005D0">ETF</a></td></tr>
      <tr><td><a href="/item/main.naver?code=00088K">우선주</a></td></tr>
    </table>
    """

    result = parse_symbols(html, market="KOSPI")

    assert [row.code for row in result] == ["0005D0", "00088K"]


def test_parse_etf_codes_preserves_alphanumeric_codes():
    payload = '{"result":{"etfItemList":[{"itemcode":"0005D0"},{"itemcode":"0167A0"}]}}'

    assert parse_etf_codes(payload) == {"0005D0", "0167A0"}


@pytest.mark.parametrize(
    "kind,list_key",
    [("etf", "etfItemList"), ("etn", "etnItemList")],
)
def test_parse_naver_fund_symbols_preserves_code_name_and_type(kind, list_key):
    payload = json.dumps({
        "resultCode": "success",
        "result": {list_key: [{"itemcode": "0005D0", "itemname": "Sample fund"}]},
    })

    result = parse_naver_fund_symbols(payload, list_key=list_key, symbol_type=kind)

    assert [(row.code, row.name, row.market, row.symbol_type) for row in result] == [
        ("0005D0", "Sample fund", "KOSPI", kind)
    ]


def test_parse_naver_individual_stock_page_parses_rows_and_pagination():
    payload = json.dumps({
        "index": "0", "size": "2", "totalCount": "3", "hasNext": True,
        "items": [
            {"itemCode": "0005D0", "itemName": "Alpha", "marketType": "KOSPI"},
            {"itemCode": "00088K", "itemName": "Beta", "marketType": "KOSDAQ"},
        ],
    })

    symbols, total_count, has_next = parse_naver_individual_stock_page(
        payload,
        expected_index=0,
    )

    assert [(row.code, row.market) for row in symbols] == [
        ("0005D0", "KOSPI"), ("00088K", "KOSDAQ")
    ]
    assert total_count == 3
    assert has_next is True


@pytest.mark.parametrize(
    "payload",
    [
        '{"items": []}',
        json.dumps({"index": "0", "size": "2", "totalCount": "3", "hasNext": False, "items": []}),
        json.dumps({"index": "1", "size": "2", "totalCount": "3", "hasNext": False, "items": []}),
        json.dumps({"index": "0", "size": "2", "totalCount": "3", "hasNext": True,
                    "items": [{"itemCode": "123", "itemName": "Bad", "marketType": "KOSPI"}]}),
        json.dumps({"index": "0", "size": "2", "totalCount": "3", "hasNext": True,
                    "items": [{"itemCode": "005930", "itemName": "Wrong market", "marketType": "KONEX"}]}),
    ],
)
def test_parse_naver_individual_stock_page_rejects_invalid_contract(payload):
    with pytest.raises(PriceParseError):
        parse_naver_individual_stock_page(payload, expected_index=0)


def test_parse_daily_prices_parses_rows_and_skips_blank_lines():
    html = (FIXTURE_DIR / "prices_005930.html").read_text(encoding="utf-8")

    result = parse_daily_prices(html)

    assert len(result) == 2
    assert result[0].trade_date == date(2026, 4, 4)
    assert result[0].close == Decimal("61500")
    assert result[0].volume == 12345678


def test_parse_benchmark_prices_parses_expected_rows():
    html = (FIXTURE_DIR / "benchmark_kospi.html").read_text(encoding="utf-8")

    result = parse_benchmark_prices(html, market="KOSPI", benchmark_code="KOSPI_INDEX")

    assert len(result) == 2
    assert result[0].benchmark_code == "KOSPI_INDEX"
    assert result[0].market == "KOSPI"
    assert result[0].trade_date == date(2026, 4, 4)
    assert result[0].close == Decimal("2780.55")


def test_parse_naver_index_prices_maps_daily_json_fields():
    payload = '''{
      "resultCode": "success",
      "result": {"siseList": [{
        "cd": "KOSPI", "dt": "20260930", "ncv": "3455.37",
        "cv": "12.34", "cr": "0.36", "ov": "3440.00",
        "hv": "3460.00", "lv": "3438.50"
      }]}
    }'''

    result = parse_naver_index_prices(
        payload,
        market="KOSPI",
        benchmark_code="KOSPI_INDEX",
        expected_naver_code="KOSPI",
    )

    assert len(result) == 1
    assert result[0].trade_date == date(2026, 9, 30)
    assert result[0].open == Decimal("3440.00")
    assert result[0].high == Decimal("3460.00")
    assert result[0].low == Decimal("3438.50")
    assert result[0].close == Decimal("3455.37")
    assert result[0].change_rate == Decimal("0.0036")
    assert result[0].volume is None


def test_parse_naver_index_prices_rejects_wrong_market_response():
    payload = '''{"resultCode":"success","result":{"siseList":[{
      "cd":"KOSDAQ","dt":"20260930","ncv":"850.0","cv":"1.0",
      "cr":"0.1","ov":"849.0","hv":"851.0","lv":"848.0"
    }]}}'''

    with pytest.raises(PriceParseError):
        parse_naver_index_prices(
            payload,
            market="KOSPI",
            benchmark_code="KOSPI_INDEX",
            expected_naver_code="KOSPI",
        )


@pytest.mark.parametrize(
    "row",
    [
        {
            "cd": "KOSPI", "dt": "2026930", "ncv": "3455.37", "cv": "12.34",
            "cr": "0.36", "ov": "3440.00", "hv": "3460.00", "lv": "3438.50",
        },
        {
            "cd": "KOSPI", "dt": "20260930", "ncv": "3455.37", "cv": "12.34",
            "cr": "0.36", "ov": "3440.00", "hv": "3430.00", "lv": "3438.50",
        },
    ],
)
def test_parse_naver_index_prices_rejects_invalid_date_or_ohlc(row):
    payload = json.dumps({"resultCode": "success", "result": {"siseList": [row]}})

    with pytest.raises(PriceParseError):
        parse_naver_index_prices(
            payload,
            market="KOSPI",
            benchmark_code="KOSPI_INDEX",
            expected_naver_code="KOSPI",
        )
