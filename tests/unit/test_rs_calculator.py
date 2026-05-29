from datetime import date, timedelta
from decimal import Decimal

from app.schemas.market_data import BenchmarkPricePayload, DailyPricePayload
from app.services.rs.calculator import SymbolSeries, calculate_market_rs


def make_series(start_close: int, step: int, days: int = 260):
    start = date(2025, 1, 1)
    rows = []
    for index in range(days):
        close = Decimal(start_close + step * index)
        rows.append(
            DailyPricePayload(
                trade_date=start + timedelta(days=index),
                open=close,
                high=close,
                low=close,
                close=close,
                volume=1000,
                change_rate=Decimal("0"),
            )
        )
    return rows


def make_benchmark(market: str, start_close: int, step: int, days: int = 260):
    start = date(2025, 1, 1)
    benchmark_code = "KOSPI_INDEX" if market == "KOSPI" else "KOSDAQ_INDEX"
    rows = []
    for index in range(days):
        close = Decimal(start_close + step * index)
        rows.append(
            BenchmarkPricePayload(
                benchmark_code=benchmark_code,
                market=market,
                trade_date=start + timedelta(days=index),
                open=close,
                high=close,
                low=close,
                close=close,
                volume=None,
                change_rate=Decimal("0"),
            )
        )
    return rows


def test_calculate_market_rs_ranks_symbols_within_market():
    benchmark = make_benchmark("KOSPI", 100, 1)
    series = [
        SymbolSeries(code="AAA", market="KOSPI", prices=make_series(100, 2)),
        SymbolSeries(code="BBB", market="KOSPI", prices=make_series(100, 1)),
    ]

    result = calculate_market_rs("KOSPI", series, benchmark)

    assert result[0].code == "AAA"
    assert result[0].rank_in_market == 1
    assert result[0].rs_rating >= result[1].rs_rating
