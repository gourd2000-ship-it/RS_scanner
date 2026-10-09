"""Backtest worker claim and single-writer behavior in an isolated PostgreSQL schema."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
import json
import os
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401 -- register schema dependencies
from app.core.base import Base
from app.models.backtest_dataset import BacktestDataset, BacktestDatasetPrice, BacktestDatasetRs, BacktestDatasetRsRun
from app.models.backtest_run import BacktestDailyEquity, BacktestRun
from app.repositories.backtest_repository import BacktestRepository, BenchmarkSnapshotInput
from app.services.backtest.execution import BacktestExecutionService
from app.services.backtest.worker import BacktestExecutionWorker


TEST_DATABASE_URL = (
    "postgresql+psycopg://rs_scanner_test:rs_scanner_test_pass@localhost:5433/rs_scanner_test"
)


@pytest.fixture
def postgres_sessions():
    database_url = os.getenv("TEST_DATABASE_URL", TEST_DATABASE_URL)
    parsed_url = make_url(database_url)
    # Fail closed if a developer points TEST_DATABASE_URL anywhere other than
    # the dedicated local test database. Never use DATABASE_URL here.
    if (
        parsed_url.database != "rs_scanner_test"
        or parsed_url.port != 5433
        or parsed_url.host not in {"localhost", "127.0.0.1", "::1"}
    ):
        pytest.skip("backtest worker PostgreSQL test requires localhost:5433/rs_scanner_test")

    admin_engine = create_engine(database_url, pool_pre_ping=True)
    schema = "backtest_worker_test_" + uuid4().hex
    schema_created = False
    try:
        try:
            with admin_engine.begin() as connection:
                connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            schema_created = True
        except SQLAlchemyError as exc:
            pytest.skip(f"isolated PostgreSQL unavailable: {type(exc).__name__}")

        schema_engine = create_engine(
            database_url,
            pool_pre_ping=True,
            connect_args={"options": f"-csearch_path={schema}"},
        )
        try:
            with schema_engine.begin() as connection:
                Base.metadata.create_all(connection)
            yield sessionmaker(bind=schema_engine, autoflush=False, expire_on_commit=False)
        finally:
            schema_engine.dispose()
            if schema_created:
                with admin_engine.begin() as connection:
                    connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
    finally:
        admin_engine.dispose()


def _strategy_config() -> dict:
    return {
        "markets": ["KOSPI"], "rebalance_interval_days": 1, "max_holdings": 1,
        "max_position_weight": "1", "cash_reserve_ratio": "0", "buy_fee_rate": "0",
        "sell_fee_rate": "0", "buy_slippage_rate": "0", "sell_slippage_rate": "0",
        "buy_conditions": {"type": "rule", "field": "rs_rating", "operator": "gte", "value": 80},
        "sell_conditions": {"type": "rule", "field": "rs_rating", "operator": "lt", "value": 80},
        "stop_loss_rate": None, "take_profit_rate": None, "max_holding_days": None,
    }


def _enqueue_pair(session: Session) -> tuple[BacktestRun, BacktestRun]:
    dates = [date(2024, 1, 2) + timedelta(days=offset) for offset in range(4)]
    manifest = {"publication_scope": "complete_segments_only", "fixture": "worker-postgres"}
    manifest_hash = sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    dataset = BacktestDataset(
        dataset_id="worker-postgres-" + uuid4().hex,
        manifest_hash=sha256(uuid4().hex.encode()).hexdigest(),
        final_manifest_hash=manifest_hash,
        range_start=dates[0], range_end=dates[-1], markets=["KOSPI"],
        reconstruction_mode="integration_fixture", adjustment_policy="fixture:1", policy_version="v1",
        manifest=manifest, status="active",
    )
    session.add(dataset)
    session.flush()
    rs_run = BacktestDatasetRsRun(
        backtest_dataset_id=dataset.id, formula_version="rs-v1", policy_version="v1",
        input_hash="a" * 64, result_hash="b" * 64, status="completed", manifest={},
    )
    session.add(rs_run)
    session.flush()
    for index, trade_date in enumerate(dates):
        close = Decimal(100 + index)
        session.add(BacktestDatasetPrice(
            backtest_dataset_id=dataset.id, instrument_id=1, source_symbol_id=1,
            code="000001", name="fixture", market="KOSPI", trade_date=trade_date,
            open=close, high=close, low=close, close=close, volume=100,
            change_rate=Decimal("0"), provider="fixture",
        ))
        session.add(BacktestDatasetRs(
            backtest_dataset_rs_run_id=rs_run.id, backtest_dataset_id=dataset.id,
            instrument_id=1, code="000001", market="KOSPI", trade_date=trade_date,
            status="available", required_observations=1, available_observations=1,
            rs_rating=90, rank_in_market=1, input_hash="c" * 64,
        ))

    repository = BacktestRepository(session)
    version = repository.create_strategy(name="PostgreSQL worker fixture", config=_strategy_config()).versions[0]
    snapshots = tuple(
        BenchmarkSnapshotInput(
            market=market, benchmark_code=market, snapshot_hash="d" * 64,
            prices=tuple((trade_date, Decimal("100")) for trade_date in dates),
        )
        for market in ("KOSPI", "KOSDAQ")
    )
    common = dict(
        strategy_version_id=version.id, dataset_id=dataset.dataset_id,
        dataset_manifest_hash=dataset.final_manifest_hash, rs_run_id=rs_run.id,
        rs_result_hash=rs_run.result_hash, range_start=dates[0], range_end=dates[-1],
        markets=["KOSPI"], benchmark_snapshots=snapshots,
    )
    first = repository.enqueue_run(**common, run_id="worker-first-" + uuid4().hex)
    second = repository.enqueue_run(**common, run_id="worker-second-" + uuid4().hex)
    return first, second


def test_postgres_worker_exposes_running_and_serializes_claims(postgres_sessions, monkeypatch):
    with postgres_sessions.begin() as session:
        first, second = _enqueue_pair(session)

    entered_execution = Event()
    release_execution = Event()
    original_execute = BacktestExecutionService.execute

    def pause_first_run(self, run):
        if run.run_id == first.run_id:
            entered_execution.set()
            if not release_execution.wait(timeout=15):
                raise TimeoutError("test did not release the first worker")
        elif run.run_id == second.run_id:
            raise AssertionError("the second worker claimed while another run was active")
        return original_execute(self, run)

    monkeypatch.setattr(BacktestExecutionService, "execute", pause_first_run)
    worker = BacktestExecutionWorker(postgres_sessions)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(worker.run_once)
        try:
            assert entered_execution.wait(timeout=10), "first worker did not enter simulation"
            with postgres_sessions() as observer:
                first_during_run = observer.scalar(
                    select(BacktestRun).where(BacktestRun.run_id == first.run_id)
                )
                second_during_run = observer.scalar(
                    select(BacktestRun).where(BacktestRun.run_id == second.run_id)
                )
                assert first_during_run is not None and first_during_run.status == "running"
                assert second_during_run is not None and second_during_run.status == "queued"

            second_outcome = BacktestExecutionWorker(postgres_sessions).run_once()
            assert second_outcome.status == "idle"
        finally:
            release_execution.set()

        first_outcome = future.result(timeout=30)

    assert first_outcome.run_id == first.run_id
    assert first_outcome.status == "completed"
    with postgres_sessions() as session:
        first_stored = session.scalar(select(BacktestRun).where(BacktestRun.run_id == first.run_id))
        second_stored = session.scalar(select(BacktestRun).where(BacktestRun.run_id == second.run_id))
        assert first_stored is not None and first_stored.status == "completed"
        assert second_stored is not None and second_stored.status == "queued"
        first_equity_count = session.scalar(
            select(func.count(BacktestDailyEquity.id)).where(
                BacktestDailyEquity.backtest_run_id == first_stored.id
            )
        )
        second_equity_count = session.scalar(
            select(func.count(BacktestDailyEquity.id)).where(
                BacktestDailyEquity.backtest_run_id == second_stored.id
            )
        )
        assert first_equity_count == 4
        assert second_equity_count == 0


def test_complete_dataset_request_worker_and_result_api_flow(postgres_sessions, monkeypatch):
    """Exercise the registered API and explicit worker against an isolated complete dataset."""
    import importlib
    from hashlib import sha256

    from fastapi.testclient import TestClient

    from app.api.v1.endpoints.backtest_auth import require_backtest_csrf, require_backtest_operator
    from app.core import database
    from app.core.database import get_db_session
    from app.models.backtest_dataset import BacktestDatasetMembership
    from app.models.benchmark import Benchmark
    from app.models.benchmark_daily_price import BenchmarkDailyPrice

    monkeypatch.setattr(database, "init_db", lambda: None)
    main_api = importlib.import_module("app.main_api")
    app = main_api.app
    dates = [date(2024, 1, 2) + timedelta(days=offset) for offset in range(4)]
    manifest = {"publication_scope": "complete_segments_only", "fixture": "backtest-api-worker"}
    final_manifest_hash = sha256(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    with postgres_sessions.begin() as session:
        dataset = BacktestDataset(
            dataset_id="complete-flow-" + uuid4().hex,
            manifest_hash=sha256(uuid4().hex.encode()).hexdigest(),
            final_manifest_hash=final_manifest_hash,
            range_start=dates[0], range_end=dates[-1], markets=["KOSPI", "KOSDAQ"],
            reconstruction_mode="integration_fixture", adjustment_policy="fixture:1",
            policy_version="v1", manifest=manifest, status="active",
        )
        session.add(dataset)
        session.flush()
        rs_run = BacktestDatasetRsRun(
            backtest_dataset_id=dataset.id, formula_version="complete-flow-rs-v1",
            policy_version="v1", input_hash="a" * 64, result_hash="b" * 64,
            status="completed", manifest={},
        )
        session.add(rs_run)
        session.flush()

        for market, instrument_id, code in (("KOSPI", 1, "000001"), ("KOSDAQ", 2, "000002")):
            for offset, trade_date in enumerate(dates):
                close = Decimal(100 + offset)
                session.add(BacktestDatasetMembership(
                    backtest_dataset_id=dataset.id, instrument_id=instrument_id,
                    trade_date=trade_date, market=market, security_type="stock",
                    membership_evidence_state="observed", trading_status="trading",
                    price_expectation="expected", event_revision_hashes=[],
                    code=code, name="integration fixture", quality_status="complete",
                ))
                session.add(BacktestDatasetPrice(
                    backtest_dataset_id=dataset.id, instrument_id=instrument_id,
                    source_symbol_id=instrument_id, code=code, name="integration fixture",
                    market=market, trade_date=trade_date, open=close, high=close + 1,
                    low=close - 1, close=close, volume=1_000 + offset,
                    change_rate=Decimal("0"), provider="fixture", adjustment_type="1",
                ))
                session.add(BacktestDatasetRs(
                    backtest_dataset_rs_run_id=rs_run.id, backtest_dataset_id=dataset.id,
                    instrument_id=instrument_id, code=code, market=market,
                    trade_date=trade_date, status="available", required_observations=1,
                    available_observations=1, rs_rating=90, rank_in_market=1,
                    input_hash="c" * 64,
                ))

        for market in ("KOSPI", "KOSDAQ"):
            benchmark = Benchmark(benchmark_code=market, name=market, market=market)
            session.add(benchmark)
            session.flush()
            for offset, trade_date in enumerate(dates):
                close = Decimal(2_000 + offset)
                session.add(BenchmarkDailyPrice(
                    benchmark_id=benchmark.id, trade_date=trade_date,
                    open=close, high=close + 1, low=close - 1, close=close,
                    volume=100_000, change_rate=Decimal("0"),
                ))

        version = BacktestRepository(session).create_strategy(
            name="Complete dataset API flow", config=_strategy_config()
        ).versions[0]

    original_overrides = app.dependency_overrides.copy()

    def override_db():
        with postgres_sessions() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[require_backtest_csrf] = lambda: object()
    app.dependency_overrides[require_backtest_operator] = lambda: object()
    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/api/v1/backtests/runs",
                json={"strategy_version_id": version.id, "start": dates[0].isoformat(), "end": dates[-1].isoformat()},
            )
            assert create_response.status_code == 201, create_response.text
            queued = create_response.json()
            assert queued["status"] == "queued"
            assert queued["dataset_manifest_hash"] == final_manifest_hash
            assert queued["rs_run_id"] is not None

            outcome = BacktestExecutionWorker(postgres_sessions).run_once()
            assert outcome.run_id == queued["run_id"]
            assert outcome.status == "completed"

            result_response = client.get(f"/api/v1/backtests/runs/{queued['run_id']}")
            assert result_response.status_code == 200, result_response.text
            result = result_response.json()
            assert result["run"]["status"] == "completed"
            assert result["metrics"] is not None
            assert result["orders"]["total_count"] > 0
            assert result["equity_curve"]
            assert set(result["benchmarks"]) == {"kospi", "kosdaq"}
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
