from datetime import date
from pathlib import Path
from decimal import Decimal

from app.crawler.parsers.benchmarks import parse_benchmark_prices
from app.crawler.parsers.prices import parse_daily_prices
from app.crawler.parsers.symbols import parse_symbols


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "naver"


def test_parse_symbols_deduplicates_and_keeps_market():
    html = (FIXTURE_DIR / "symbols_kospi.html").read_text(encoding="utf-8")

    result = parse_symbols(html, market="KOSPI")

    assert len(result) == 2
    assert {row.code for row in result} == {"005930", "000660"}
    assert all(row.market == "KOSPI" for row in result)


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
