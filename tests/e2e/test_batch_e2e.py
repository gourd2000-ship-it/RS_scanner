"""배치 파이프라인 E2E 테스트 (PostgreSQL)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.benchmark import Benchmark
from app.models.benchmark_daily_price import BenchmarkDailyPrice
from app.models.crawl_job import CrawlJob
from app.models.daily_price import DailyPrice
from app.models.data_quality import (
    BenchmarkObservation,
    PriceObservation,
    RsInputSnapshot,
    RsRun,
    ValidationRun,
)
from app.models.rs_score import RsScore
from app.models.symbol import Symbol
from app.schemas.market_data import BenchmarkPricePayload, DailyPricePayload, SymbolPayload
from app.services.batch.context import BatchContext
from app.services.batch.run_daily_job import run_daily_job
from tests.harness.fake_source import FakePriceSource


def make_prices(start_close: int, step: int, days: int = 260):
    """테스트용 가격 데이터 생성."""
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
    """테스트용 벤치마크 데이터 생성."""
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


@pytest.mark.e2e
def test_full_batch_pipeline_e2e(e2e_batch_context: BatchContext, e2e_session: Session):
    """전체 배치 파이프라인 E2E 테스트 (sync_symbols → sync_benchmarks → sync_prices → calculate_rs)."""
    # Given: 테스트용 데이터 소스
    symbols = [
        SymbolPayload(code="005930", name="삼성전자", market="KOSPI"),
        SymbolPayload(code="000660", name="SK하이닉스", market="KOSPI"),
        SymbolPayload(code="035720", name="카카오", market="KOSDAQ"),
    ]
    source = FakePriceSource(
        symbols=symbols,
        prices_by_code={
            "005930": make_prices(70000, 100, 260),
            "000660": make_prices(130000, 200, 260),
            "035720": make_prices(50000, 50, 260),
        },
        benchmark_prices_by_market={
            "KOSPI": make_benchmark("KOSPI", 260),
            "KOSDAQ": make_benchmark("KOSDAQ", 260),
        },
    )

    # When: 전체 배치 파이프라인 실행
    result = run_daily_job(e2e_batch_context, source)

    # Then: 배치 실행 결과 검증
    assert result["symbols"] == 3
    assert result["benchmarks"]["KOSPI"] == 260
    assert result["benchmarks"]["KOSDAQ"] == 260
    assert result["prices"]["005930"] == 260
    assert result["prices"]["000660"] == 260
    assert result["prices"]["035720"] == 260
    assert result["rs_results"]["KOSPI"] == 2
    assert result["rs_results"]["KOSDAQ"] == 1

    # Then: DB에 저장된 데이터 검증
    # 1. Symbols
    saved_symbols = e2e_session.query(Symbol).all()
    assert len(saved_symbols) == 3
    assert {s.code for s in saved_symbols} == {"005930", "000660", "035720"}

    # 2. Benchmarks
    saved_benchmarks = e2e_session.query(Benchmark).all()
    assert len(saved_benchmarks) == 2
    assert {b.benchmark_code for b in saved_benchmarks} == {"KOSPI_INDEX", "KOSDAQ_INDEX"}

    # 3. DailyPrices
    saved_prices = e2e_session.query(DailyPrice).count()
    assert saved_prices == 260 * 3  # 3종목 * 260일

    # 4. BenchmarkDailyPrices
    saved_benchmark_prices = e2e_session.query(BenchmarkDailyPrice).count()
    assert saved_benchmark_prices == 260 * 2  # 2벤치마크 * 260일

    # 5. RsScores
    saved_rs_scores = e2e_session.query(RsScore).all()
    assert len(saved_rs_scores) == 3
    assert {rs.market for rs in saved_rs_scores} == {"KOSPI", "KOSDAQ"}

    # 6. CrawlJobs
    saved_jobs = e2e_session.query(CrawlJob).all()
    assert len(saved_jobs) >= 1
    latest_job = sorted(saved_jobs, key=lambda j: j.started_at)[-1]
    assert latest_job.status == "completed"
    assert latest_job.symbols_total == 3
    assert latest_job.symbols_succeeded == 3
    assert latest_job.symbols_failed == 0

    # 7. Validation and lineage records
    validation_run = e2e_session.query(ValidationRun).one()
    assert validation_run.validation_status in {"passed", "passed_with_warnings"}
    assert validation_run.expected_symbols == 3
    assert e2e_session.query(PriceObservation).count() == 260 * 3
    assert e2e_session.query(BenchmarkObservation).count() == 260 * 2
    rs_run = e2e_session.query(RsRun).one()
    assert rs_run.status == "completed"
    assert rs_run.validation_run_id == validation_run.id
    assert e2e_session.query(RsInputSnapshot).count() == 3
    assert all(row.rs_run_id == rs_run.id for row in saved_rs_scores)
    validated_count = e2e_session.scalar(
        text("SELECT count(*) FROM v_daily_prices_validated")
    )
    rs_input_count = e2e_session.scalar(
        text("SELECT count(*) FROM v_rs_input_prices")
    )
    assert validated_count == saved_prices
    assert rs_input_count == saved_prices


@pytest.mark.e2e
def test_incremental_sync_e2e(e2e_batch_context: BatchContext, e2e_session: Session):
    """증분 동기화 E2E 테스트 (이미 저장된 데이터는 재크롤링하지 않음)."""
    # Given: 첫 번째 배치 실행
    symbols = [
        SymbolPayload(code="005930", name="삼성전자", market="KOSPI"),
    ]
    all_prices = make_prices(70000, 100, 260)
    all_benchmark_prices = make_benchmark("KOSPI", 260)

    source = FakePriceSource(
        symbols=symbols,
        prices_by_code={"005930": all_prices},
        benchmark_prices_by_market={
            "KOSPI": all_benchmark_prices,
            "KOSDAQ": make_benchmark("KOSDAQ", 260),
        },
    )

    first_result = run_daily_job(e2e_batch_context, source)
    assert first_result["prices"]["005930"] == 260

    # When: 두 번째 배치 실행 (같은 데이터)
    second_result = run_daily_job(e2e_batch_context, source)

    # Then: 증분 크롤링으로 중복 데이터 스킵
    # 새로운 데이터가 없으므로 0개 추가됨
    assert second_result["prices"]["005930"] == 260  # 전체 개수는 동일
    assert second_result["benchmarks"]["KOSPI"] == 260

    # DB에 저장된 가격 데이터 개수 확인 (중복 저장 방지)
    saved_prices = e2e_session.query(DailyPrice).count()
    assert saved_prices == 260  # 중복 없이 260개만 저장


@pytest.mark.e2e
def test_rs_calculation_accuracy_e2e(e2e_batch_context: BatchContext, e2e_session: Session):
    """RS 계산 정확도 E2E 테스트."""
    # Given: 명확한 수익률 패턴을 가진 종목들
    # - 종목 A: 큰 상승 (step=500)
    # - 종목 B: 작은 상승 (step=100)
    symbols = [
        SymbolPayload(code="A00001", name="강한종목", market="KOSPI"),
        SymbolPayload(code="B00001", name="약한종목", market="KOSPI"),
    ]
    source = FakePriceSource(
        symbols=symbols,
        prices_by_code={
            "A00001": make_prices(10000, 500, 260),  # 큰 상승
            "B00001": make_prices(10000, 100, 260),  # 작은 상승
        },
        benchmark_prices_by_market={
            "KOSPI": make_benchmark("KOSPI", 260),
            "KOSDAQ": make_benchmark("KOSDAQ", 260),
        },
    )

    # When: 배치 실행
    result = run_daily_job(e2e_batch_context, source)

    # Then: RS 결과 검증
    assert result["rs_results"]["KOSPI"] == 2

    # DB에서 RS 점수 조회
    rs_scores = e2e_session.query(RsScore).order_by(RsScore.rs_rating.desc()).all()
    assert len(rs_scores) == 2

    # 강한 종목이 더 높은 RS Rating을 가져야 함
    strong_symbol = e2e_session.query(Symbol).filter(Symbol.code == "A00001").first()
    weak_symbol = e2e_session.query(Symbol).filter(Symbol.code == "B00001").first()

    strong_rs = next(rs for rs in rs_scores if rs.symbol_id == strong_symbol.id)
    weak_rs = next(rs for rs in rs_scores if rs.symbol_id == weak_symbol.id)

    assert strong_rs.rs_rating > weak_rs.rs_rating
    assert strong_rs.rank_in_market == 1
    assert weak_rs.rank_in_market == 2


@pytest.mark.e2e
def test_crawl_job_tracking_e2e(e2e_batch_context: BatchContext, e2e_session: Session):
    """크롤링 작업 추적 E2E 테스트."""
    # Given: 테스트용 데이터 소스
    symbols = [
        SymbolPayload(code="005930", name="삼성전자", market="KOSPI"),
    ]
    source = FakePriceSource(
        symbols=symbols,
        prices_by_code={"005930": make_prices(70000, 100, 260)},
        benchmark_prices_by_market={
            "KOSPI": make_benchmark("KOSPI", 260),
            "KOSDAQ": make_benchmark("KOSDAQ", 260),
        },
    )

    # When: 배치 실행
    result = run_daily_job(e2e_batch_context, source)

    # Then: CrawlJob 레코드가 생성되었는지 확인
    assert "job_id" in result

    # DB에서 작업 조회
    job = e2e_session.query(CrawlJob).filter(CrawlJob.id == result["job_id"]).first()
    assert job is not None
    assert job.status == "completed"
    assert job.finished_at is not None
    assert job.symbols_total == 1
    assert job.symbols_succeeded == 1
    assert job.symbols_failed == 0


@pytest.mark.e2e
def test_multiple_markets_e2e(e2e_batch_context: BatchContext, e2e_session: Session):
    """여러 시장 동시 처리 E2E 테스트."""
    # Given: KOSPI와 KOSDAQ 종목들
    symbols = [
        SymbolPayload(code="K001", name="KOSPI1", market="KOSPI"),
        SymbolPayload(code="K002", name="KOSPI2", market="KOSPI"),
        SymbolPayload(code="Q001", name="KOSDAQ1", market="KOSDAQ"),
        SymbolPayload(code="Q002", name="KOSDAQ2", market="KOSDAQ"),
    ]
    source = FakePriceSource(
        symbols=symbols,
        prices_by_code={
            "K001": make_prices(10000, 100, 260),
            "K002": make_prices(20000, 200, 260),
            "Q001": make_prices(5000, 50, 260),
            "Q002": make_prices(15000, 150, 260),
        },
        benchmark_prices_by_market={
            "KOSPI": make_benchmark("KOSPI", 260),
            "KOSDAQ": make_benchmark("KOSDAQ", 260),
        },
    )

    # When: 배치 실행
    result = run_daily_job(e2e_batch_context, source)

    # Then: 각 시장별 RS 계산 검증
    assert result["rs_results"]["KOSPI"] == 2
    assert result["rs_results"]["KOSDAQ"] == 2

    # 각 시장별로 독립적인 랭킹이 매겨져야 함
    kospi_rs = e2e_session.query(RsScore).filter(RsScore.market == "KOSPI").all()
    kosdaq_rs = e2e_session.query(RsScore).filter(RsScore.market == "KOSDAQ").all()

    assert len(kospi_rs) == 2
    assert len(kosdaq_rs) == 2

    # 각 시장 내에서 rank_in_market은 1, 2여야 함
    kospi_ranks = {rs.rank_in_market for rs in kospi_rs}
    kosdaq_ranks = {rs.rank_in_market for rs in kosdaq_rs}

    assert kospi_ranks == {1, 2}
    assert kosdaq_ranks == {1, 2}
