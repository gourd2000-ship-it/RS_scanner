"""E2E 통합 테스트용 픽스처."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.base import Base
from app.core.database import get_db_session
from app.main_api import app
from app.repositories.benchmark_repository import BenchmarkRepository
from app.repositories.crawl_failure_repository import CrawlFailureRepository
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.repositories.price_repository import PriceRepository
from app.repositories.rs_repository import RsRepository
from app.repositories.symbol_repository import SymbolRepository
from app.services.batch.context import BatchContext

# E2E 테스트용 PostgreSQL 데이터베이스
# docker-compose.test.yml에서 실행된 DB에 연결
E2E_DATABASE_URL = os.getenv(
    "E2E_DATABASE_URL",
    "postgresql+psycopg://rs_scanner_test:rs_scanner_test_pass@localhost:5433/rs_scanner_test",
)

# 프로젝트 루트 디렉토리
PROJECT_ROOT = Path(__file__).parent.parent.parent


@pytest.fixture(scope="session")
def e2e_engine():
    """E2E 테스트용 DB 엔진 생성 (세션 스코프)."""
    engine = create_engine(E2E_DATABASE_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def setup_db(e2e_engine):
    """E2E 테스트 DB 초기화 및 마이그레이션 실행."""
    # E2E 전용 DB는 테스트 실행마다 비우고 시작한다. ``drop_all``만
    # 사용하면 Alembic의 버전 테이블이 남아, 다음 실행에서 마이그레이션이
    # 이미 적용된 것으로 오인될 수 있다.
    with e2e_engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))

    # Alembic 마이그레이션 실행
    env = os.environ.copy()
    env["DATABASE_URL"] = E2E_DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        # 마이그레이션 실패 시 테이블 직접 생성 (대체 수단)
        print(f"Alembic migration failed: {result.stderr}")
        print("Creating tables directly...")
        Base.metadata.create_all(bind=e2e_engine)

    yield

    # 테스트 종료 후 모든 테이블 삭제
    with e2e_engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


@pytest.fixture(scope="function")
def e2e_session(e2e_engine, setup_db):
    """E2E 테스트용 DB 세션 생성 (트랜잭션 사용)."""
    connection = e2e_engine.connect()
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
def e2e_client(e2e_session: Session):
    """FastAPI TestClient with E2E DB session."""

    def override_get_db():
        try:
            yield e2e_session
        finally:
            pass

    app.dependency_overrides[get_db_session] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def e2e_batch_context(e2e_session: Session):
    """E2E 테스트용 배치 컨텍스트 (실제 DB 기반)."""
    return BatchContext(
        symbol_repository=SymbolRepository(e2e_session),
        benchmark_repository=BenchmarkRepository(e2e_session),
        price_repository=PriceRepository(e2e_session),
        rs_repository=RsRepository(e2e_session),
        crawl_job_repository=CrawlJobRepository(e2e_session),
        crawl_failure_repository=CrawlFailureRepository(e2e_session),
        session=e2e_session,
    )
