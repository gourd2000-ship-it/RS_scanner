from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.base import Base
import app.models  # noqa: F401
from app.crawler.sources.krx import KrxUniverseFetchResult
from app.repositories.krx_universe_repository import KrxUniverseRepository
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


def test_batch_crawls_etf_and_etn_but_publishes_rs_for_stocks_only():
    symbols = [
        SymbolPayload(code="000001", name="Alpha", market="KOSPI"),
        SymbolPayload(
            code="0005D0",
            name="KODEX 미국S&P500커버드콜",
            market="KOSPI",
            symbol_type="etf",
        ),
        SymbolPayload(
            code="0013R0",
            name="테스트 ETN",
            market="KOSPI",
            symbol_type="etn",
        ),
    ]
    source = FakePriceSource(
        symbols=symbols,
        prices_by_code={
            "000001": make_prices(100, 2),
            "0005D0": make_prices(100, 3),
            "0013R0": make_prices(100, 4),
        },
        benchmark_prices_by_market={
            "KOSPI": make_benchmark("KOSPI"),
            "KOSDAQ": make_benchmark("KOSDAQ"),
        },
    )

    result = run_daily_job(build_memory_batch_context(), source)

    assert result["symbols"] == 3
    assert set(result["prices"]) == {"000001", "0005D0", "0013R0"}
    assert result["rs_results"] == {"KOSPI": 1}


def test_partial_krx_shadow_snapshot_does_not_block_naver_prices():
    class PartialKrxSource:
        def fetch_stock_membership(self, as_of_date: date) -> KrxUniverseFetchResult:
            return KrxUniverseFetchResult(
                as_of_date=as_of_date,
                members=[],
                complete=False,
                error_message="KOSDAQ:KrxUniverseFetchError",
            )

    context = build_memory_batch_context()
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    context.krx_universe_repository = KrxUniverseRepository(sessionmaker(bind=engine)())
    source = FakePriceSource(
        symbols=[SymbolPayload(code="000001", name="Alpha", market="KOSPI")],
        prices_by_code={"000001": make_prices(100, 2)},
        benchmark_prices_by_market={
            "KOSPI": make_benchmark("KOSPI"),
            "KOSDAQ": make_benchmark("KOSDAQ"),
        },
    )

    result = run_daily_job(context, source, krx_source=PartialKrxSource())

    assert result["prices"]["000001"] == 260
    assert context.krx_universe_snapshot_status == "failed"
    job = context.crawl_job_repository.get_latest("daily_full")
    assert job is not None
    assert job.status == "completed_with_errors"
