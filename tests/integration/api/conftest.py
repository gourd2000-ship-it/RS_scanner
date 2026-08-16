"""API 통합 테스트용 픽스처."""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.base import Base
from app.core.database import get_db_session
from app.main_api import app


# 테스트용 PostgreSQL 데이터베이스 (별도 DB 사용)
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://rs_scanner:rs_scanner_dev@localhost:5432/rs_scanner_test",
)


@pytest.fixture(scope="session")
def test_engine():
    """테스트용 DB 엔진 생성 (세션 스코프)."""
    engine = create_engine(TEST_DATABASE_URL)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def test_session(test_engine):
    """테스트용 DB 세션 생성 (트랜잭션 사용)."""
    connection = test_engine.connect()
    transaction = connection.begin()
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=connection)
    session = TestSessionLocal()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(scope="function")
def client(test_session: Session):
    """FastAPI TestClient with test DB session."""

    def override_get_db():
        try:
            yield test_session
        finally:
            pass

    app.dependency_overrides[get_db_session] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def sample_symbols(test_session: Session):
    """샘플 종목 데이터 생성."""
    from datetime import date
    from app.models.symbol import Symbol

    symbols = [
        Symbol(
            code="005930",
            name="삼성전자",
            market="KOSPI",
            sector="전기전자",
            industry="반도체",
            is_active=True,
            listed_at=date(1975, 6, 11),
        ),
        Symbol(
            code="000660",
            name="SK하이닉스",
            market="KOSPI",
            sector="전기전자",
            industry="반도체",
            is_active=True,
            listed_at=date(1996, 12, 26),
        ),
        Symbol(
            code="035420",
            name="NAVER",
            market="KOSPI",
            sector="서비스업",
            industry="인터넷",
            is_active=True,
            listed_at=date(2002, 10, 29),
        ),
        Symbol(
            code="086520",
            name="에코프로",
            market="KOSDAQ",
            sector="제조업",
            industry="2차전지",
            is_active=True,
            listed_at=date(2007, 5, 25),
        ),
        Symbol(
            code="247540",
            name="에코프로비엠",
            market="KOSDAQ",
            sector="제조업",
            industry="2차전지",
            is_active=True,
            listed_at=date(2016, 9, 9),
        ),
    ]

    for symbol in symbols:
        test_session.add(symbol)
    test_session.commit()

    # 딕셔너리로 반환 (코드로 접근 가능)
    return {s.code: s for s in symbols}


@pytest.fixture
def sample_benchmarks(test_session: Session):
    """샘플 벤치마크 데이터 생성."""
    from datetime import datetime
    from app.models.benchmark import Benchmark

    benchmarks = [
        Benchmark(
            benchmark_code="KOSPI",
            name="코스피",
            market="KOSPI",
            created_at=datetime.utcnow(),
        ),
        Benchmark(
            benchmark_code="KOSDAQ",
            name="코스닥",
            market="KOSDAQ",
            created_at=datetime.utcnow(),
        ),
    ]

    for benchmark in benchmarks:
        test_session.add(benchmark)
    test_session.commit()

    return {b.benchmark_code: b for b in benchmarks}


@pytest.fixture
def sample_prices(test_session: Session, sample_symbols):
    """샘플 가격 데이터 생성."""
    from datetime import date, timedelta
    from decimal import Decimal
    from app.models.daily_price import DailyPrice

    prices = []
    base_date = date(2024, 5, 28)

    for i in range(30):  # 30일치 데이터
        trade_date = base_date - timedelta(days=i)

        for code, symbol in sample_symbols.items():
            base_price = 100000 if symbol.market == "KOSPI" else 50000
            price = base_price + (i * 1000)  # 단순한 가격 패턴

            prices.append(
                DailyPrice(
                    symbol_id=symbol.id,
                    trade_date=trade_date,
                    open=Decimal(str(price * 0.98)),
                    high=Decimal(str(price * 1.02)),
                    low=Decimal(str(price * 0.97)),
                    close=Decimal(str(price)),
                    volume=1000000,
                    change_rate=Decimal("0.05"),
                    source="test",
                )
            )

    for price in prices:
        test_session.add(price)
    test_session.commit()

    return prices


@pytest.fixture
def sample_rs_scores(test_session: Session, sample_symbols, sample_benchmarks):
    """샘플 RS 점수 데이터 생성."""
    from datetime import date
    from decimal import Decimal
    from app.models.rs_score import RsScore

    rs_scores = []
    trade_date = date(2024, 5, 28)

    # KOSPI 종목
    kospi_symbols = [s for s in sample_symbols.values() if s.market == "KOSPI"]
    for rank, symbol in enumerate(kospi_symbols, 1):
        rs_scores.append(
            RsScore(
                symbol_id=symbol.id,
                benchmark_id=sample_benchmarks["KOSPI"].id,
                trade_date=trade_date,
                market="KOSPI",
                return_1m=Decimal("0.02"),
                return_3m=Decimal("0.05"),
                return_6m=Decimal("0.10"),
                return_9m=Decimal("0.15"),
                return_12m=Decimal("0.20"),
                relative_return_score=Decimal(str(0.1 * (len(kospi_symbols) - rank + 1))),
                rs_percentile=Decimal(str(1.0 - (rank - 1) / len(kospi_symbols))),
                rs_rating=99 - (rank - 1) * 20,
                rank_in_market=rank,
            )
        )

    # KOSDAQ 종목
    kosdaq_symbols = [s for s in sample_symbols.values() if s.market == "KOSDAQ"]
    for rank, symbol in enumerate(kosdaq_symbols, 1):
        rs_scores.append(
            RsScore(
                symbol_id=symbol.id,
                benchmark_id=sample_benchmarks["KOSDAQ"].id,
                trade_date=trade_date,
                market="KOSDAQ",
                return_1m=Decimal("0.02"),
                return_3m=Decimal("0.05"),
                return_6m=Decimal("0.10"),
                return_9m=Decimal("0.15"),
                return_12m=Decimal("0.20"),
                relative_return_score=Decimal(str(0.1 * (len(kosdaq_symbols) - rank + 1))),
                rs_percentile=Decimal(str(1.0 - (rank - 1) / len(kosdaq_symbols))),
                rs_rating=99 - (rank - 1) * 33,
                rank_in_market=rank,
            )
        )

    for universe_rank, rs_score in enumerate(
        sorted(rs_scores, key=lambda row: (-row.relative_return_score, row.symbol_id)),
        1,
    ):
        rs_score.rank_in_universe = universe_rank

    for rs in rs_scores:
        test_session.add(rs)
    test_session.commit()

    return rs_scores


@pytest.fixture
def sample_crawl_jobs(test_session: Session):
    """샘플 크롤링 작업 데이터 생성."""
    from datetime import datetime, timedelta
    from app.models.crawl_job import CrawlJob

    jobs = [
        CrawlJob(
            job_type="sync_prices",
            started_at=datetime.utcnow() - timedelta(hours=1),
            finished_at=datetime.utcnow() - timedelta(minutes=30),
            status="completed",
            symbols_total=100,
            symbols_succeeded=98,
            symbols_failed=2,
            message="크롤링 완료",
        ),
        CrawlJob(
            job_type="sync_symbols",
            started_at=datetime.utcnow() - timedelta(hours=2),
            finished_at=None,
            status="running",
            symbols_total=50,
            symbols_succeeded=25,
            symbols_failed=0,
            message="진행 중",
        ),
    ]

    for job in jobs:
        test_session.add(job)
    test_session.commit()

    return jobs


@pytest.fixture
def sample_crawl_failures(test_session: Session, sample_crawl_jobs):
    """샘플 크롤링 실패 데이터 생성."""
    from datetime import datetime
    from app.models.crawl_failure import CrawlFailure

    failures = [
        CrawlFailure(
            job_id=sample_crawl_jobs[0].id,
            target_type="symbol",
            target_key="999999",
            url="https://finance.naver.com/item/main.nhn?code=999999",
            http_status=404,
            error_class="HTTPError",
            error_message="Not Found",
            retry_count=3,
            created_at=datetime.utcnow(),
        ),
    ]

    for failure in failures:
        test_session.add(failure)
    test_session.commit()

    return failures
