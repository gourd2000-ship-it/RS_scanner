from datetime import date, timedelta
from decimal import Decimal

from app.schemas.market_data import BenchmarkPricePayload, DailyPricePayload, SymbolPayload
from app.services.batch.context import build_memory_batch_context
from app.services.batch.run_daily_job import run_daily_job
from tests.harness.fake_source import FakePriceSource


def make_prices(start_close: int, step: int, days: int = 260):
    start = date(2025, 1, 1)
    return [
        DailyPricePayload(
            trade_date=start + timedelta(days=index),
            open=Decimal(start_close + step * index),
            high=Decimal(start_close + step * index),
            low=Decimal(start_close + step * index),
            close=Decimal(start_close + step * index),
            volume=1000,
            change_rate=Decimal("0"),
        )
        for index in range(days)
    ]


def make_benchmark(market: str, days: int = 260):
    start = date(2025, 1, 1)
    benchmark_code = "KOSPI_INDEX" if market == "KOSPI" else "KOSDAQ_INDEX"
    return [
        BenchmarkPricePayload(
            benchmark_code=benchmark_code,
            market=market,
            trade_date=start + timedelta(days=index),
            open=Decimal(100 + index),
            high=Decimal(100 + index),
            low=Decimal(100 + index),
            close=Decimal(100 + index),
            volume=None,
            change_rate=Decimal("0"),
        )
        for index in range(days)
    ]


def test_daily_batch_harness_runs_end_to_end():
    symbols = [
        SymbolPayload(code="000001", name="Alpha", market="KOSPI"),
        SymbolPayload(code="100001", name="Beta", market="KOSDAQ"),
    ]
    source = FakePriceSource(
        symbols=symbols,
        prices_by_code={
            "000001": make_prices(100, 2),
            "100001": make_prices(100, 3),
        },
        benchmark_prices_by_market={
            "KOSPI": make_benchmark("KOSPI"),
            "KOSDAQ": make_benchmark("KOSDAQ"),
        },
    )

    result = run_daily_job(build_memory_batch_context(), source)

    assert result["symbols"] == 2
    assert result["rs_results"]["KOSPI"] == 1
    assert result["rs_results"]["KOSDAQ"] == 1


def test_incremental_sync_only_fetches_new_rows():
    symbols = [
        SymbolPayload(code="000001", name="Alpha", market="KOSPI"),
    ]
    all_symbol_prices = make_prices(100, 2)
    all_benchmark_prices = make_benchmark("KOSPI")
    source = FakePriceSource(
        symbols=symbols,
        prices_by_code={"000001": all_symbol_prices},
        benchmark_prices_by_market={"KOSPI": all_benchmark_prices, "KOSDAQ": make_benchmark("KOSDAQ")},
    )
    context = build_memory_batch_context()

    first = run_daily_job(context, source)
    second = run_daily_job(context, source)

    assert first["prices"]["000001"] == len(all_symbol_prices)
    assert second["prices"]["000001"] == len(all_symbol_prices)
    assert second["benchmarks"]["KOSPI"] == len(all_benchmark_prices)
