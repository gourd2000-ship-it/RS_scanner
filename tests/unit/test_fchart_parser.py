from datetime import date
from decimal import Decimal

from app.crawler.parsers.fchart import parse_fchart_prices


SAMPLE_RESPONSE = """
 [['날짜', '시가', '고가', '저가', '종가', '거래량', '외국인소진율'],

["20260610", 1914000, 1945000, 1746000, 1805000, 1295394, 37.57],
["20260611", 1725000, 1844000, 1691000, 1805000, 1142539, 37.5],
["20260612", 1965000, 1991000, 1694000, 1714000, 1940690, 37.77]
]
"""


class TestFchartParser:
    def test_parse_valid_response(self):
        rows = parse_fchart_prices(SAMPLE_RESPONSE)
        assert len(rows) == 3
        assert rows[0].trade_date == date(2026, 6, 10)
        assert rows[0].open == Decimal("1914000")
        assert rows[0].high == Decimal("1945000")
        assert rows[0].low == Decimal("1746000")
        assert rows[0].close == Decimal("1805000")
        assert rows[0].volume == 1295394

    def test_parse_empty_string(self):
        assert parse_fchart_prices("") == []

    def test_parse_header_only(self):
        text = "[['날짜', '시가', '고가', '저가', '종가', '거래량', '외국인소진율']]"
        assert parse_fchart_prices(text) == []

    def test_single_row(self):
        text = """[['날짜','시가','고가','저가','종가','거래량','외'],
        ["20260101", 100, 110, 90, 105, 50000, 1.0]]"""
        rows = parse_fchart_prices(text)
        assert len(rows) == 1
        assert rows[0].close == Decimal("105")

    def test_dates_sorted_ascending(self):
        text = """[['날짜','시가','고가','저가','종가','거래량','외'],
        ["20260615", 100, 110, 90, 105, 1000, 0],
        ["20260610", 200, 210, 190, 205, 2000, 0],
        ["20260612", 150, 160, 140, 155, 1500, 0]]"""
        rows = parse_fchart_prices(text)
        dates = [r.trade_date for r in rows]
        assert dates == sorted(dates)

    def test_volume_zero_handled(self):
        text = """[['날짜','시가','고가','저가','종가','거래량','외'],
        ["20260501", 1000, 1000, 1000, 1000, 0, 0]]"""
        rows = parse_fchart_prices(text)
        assert len(rows) == 1
        assert rows[0].volume == 0

    def test_whitespace_tolerance(self):
        text = """  \n\n  [['날짜','시가','고가','저가','종가','거래량','외'],
        ["20260101", 100, 110, 90, 105, 50000, 1.0]]  \n  """
        rows = parse_fchart_prices(text)
        assert len(rows) == 1

    def test_change_rate_is_zero(self):
        rows = parse_fchart_prices(SAMPLE_RESPONSE)
        for r in rows:
            assert r.change_rate == Decimal("0")

    def test_invalid_json_returns_empty(self):
        assert parse_fchart_prices("not json at all") == []
