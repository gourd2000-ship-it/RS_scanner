from datetime import date
from pathlib import Path

from tests.harness.replay_source import ReplayPriceSource


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "naver"


def test_replay_source_reads_fixture_bundle():
    source = ReplayPriceSource(FIXTURE_DIR)

    symbols = source.fetch_symbols()
    kospi_prices = source.fetch_daily_prices("005930")
    kosdaq_benchmark = source.fetch_benchmark_prices("KOSDAQ")

    assert len(symbols) == 4
    assert len(kospi_prices) == 2
    assert len(kosdaq_benchmark) == 2


def test_replay_source_supports_incremental_since_date():
    source = ReplayPriceSource(FIXTURE_DIR)

    rows = source.fetch_daily_prices("005930", since_date=date(2026, 4, 3))
    benchmark_rows = source.fetch_benchmark_prices("KOSPI", since_date=date(2026, 4, 3))

    assert len(rows) == 1
    assert rows[0].trade_date == date(2026, 4, 4)
    assert len(benchmark_rows) == 1
    assert benchmark_rows[0].trade_date == date(2026, 4, 4)
