"""격리 PostgreSQL에서 백테스트 고정 입력과 종료 상태를 확인한다."""

import os
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models.backtest_dataset import BacktestDataset, BacktestDatasetRsRun
from app.models.backtest_run import BacktestRun, BacktestStrategyVersion
from app.repositories.backtest_repository import BacktestRepository, BenchmarkSnapshotInput


def _snapshots() -> tuple[BenchmarkSnapshotInput, BenchmarkSnapshotInput]:
    return (
        BenchmarkSnapshotInput("KOSPI", "KOSPI", "e" * 64, ((date(2020, 1, 2), Decimal("2000")),)),
        BenchmarkSnapshotInput("KOSDAQ", "KOSDAQ", "f" * 64, ((date(2020, 1, 2), Decimal("650")),)),
    )


def _final_manifest_hash(manifest: dict) -> str:
    return sha256(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def test_execution_storage_on_isolated_postgres_rejects_terminal_mutation():
    database_url = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://rs_scanner_test:rs_scanner_test_pass@localhost:5433/rs_scanner_test",
    )
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        try:
            connection = engine.connect()
        except Exception as exc:
            pytest.skip(f"isolated PostgreSQL unavailable: {type(exc).__name__}")
        with connection:
            transaction = connection.begin()
            try:
                with Session(bind=connection, autoflush=False) as session:
                    manifest = {"publication_scope": "complete_segments_only"}
                    dataset = BacktestDataset(
                        dataset_id="postgres-complete-dataset", manifest_hash="a" * 64,
                        final_manifest_hash=_final_manifest_hash(manifest),
                        range_start=date(2020, 1, 2), range_end=date(2020, 1, 3),
                        markets=["KOSPI", "KOSDAQ"], reconstruction_mode="historical_reconstructed",
                        adjustment_policy="fixture:1", policy_version="v1",
                        manifest=manifest, status="active",
                    )
                    session.add(dataset)
                    session.flush()
                    rs_run = BacktestDatasetRsRun(
                        backtest_dataset_id=dataset.id, formula_version="postgres-rs-v1", policy_version="v1",
                        input_hash="c" * 64, result_hash="d" * 64, manifest={},
                    )
                    session.add(rs_run)
                    session.flush()
                    repository = BacktestRepository(session)
                    strategy = repository.create_strategy(name="PostgreSQL 표본", config={})
                    for initial_status in ("running", "completed"):
                        invalid_initial_run = BacktestRun(
                            run_id=uuid4().hex,
                            backtest_strategy_version_id=strategy.versions[0].id,
                            backtest_dataset_id=dataset.id,
                            backtest_dataset_rs_run_id=rs_run.id,
                            dataset_id=dataset.dataset_id,
                            dataset_manifest_hash=dataset.final_manifest_hash,
                            rs_result_hash=rs_run.result_hash,
                            range_start=date(2020, 1, 2), range_end=date(2020, 1, 3),
                            markets=["KOSPI"], status=initial_status,
                        )
                        savepoint = session.begin_nested()
                        session.add(invalid_initial_run)
                        with pytest.raises(DBAPIError):
                            session.flush()
                        savepoint.rollback()
                    run = repository.enqueue_run(
                        strategy_version_id=strategy.versions[0].id, dataset_id=dataset.dataset_id,
                        dataset_manifest_hash=dataset.final_manifest_hash, rs_run_id=rs_run.id,
                        rs_result_hash=rs_run.result_hash, range_start=date(2020, 1, 2),
                        range_end=date(2020, 1, 3), markets=["KOSPI"], benchmark_snapshots=_snapshots(),
                    )
                    assert repository.claim_next_run().id == run.id
                    repository.transition_run(run.run_id, "completed")

                    savepoint = session.begin_nested()
                    with pytest.raises(DBAPIError):
                        session.execute(
                            update(BacktestRun).where(BacktestRun.id == run.id).values(status="failed")
                        )
                    savepoint.rollback()
                    assert session.get(BacktestRun, run.id).status == "completed"

                    savepoint = session.begin_nested()
                    with pytest.raises(DBAPIError):
                        session.execute(
                            update(BacktestStrategyVersion)
                            .where(BacktestStrategyVersion.id == strategy.versions[0].id)
                            .values(version=2)
                        )
                    savepoint.rollback()
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
