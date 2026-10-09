"""Indicator snapshot pins remain immutable in isolated PostgreSQL schemas."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError


MIGRATION_PATH = next(
    (Path(__file__).parents[2] / "alembic" / "versions").glob(
        "c1d2e3f4a5b6_*.py"
    )
)


@pytest.fixture
def connection():
    database_url = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://rs_scanner_test:rs_scanner_test_pass@localhost:5433/rs_scanner_test",
    )
    engine = create_engine(database_url)
    try:
        conn = engine.connect()
    except SQLAlchemyError as exc:
        pytest.skip(f"isolated PostgreSQL unavailable: {type(exc).__name__}")
    with conn:
        transaction = conn.begin()
        schema = "backtest_run_indicator_test_" + uuid4().hex
        conn.exec_driver_sql(f"CREATE SCHEMA {schema}")
        conn.exec_driver_sql(f"SET LOCAL search_path TO {schema}")
        conn.exec_driver_sql("""
            CREATE TABLE backtest_dataset_indicator_snapshots (
                id integer PRIMARY KEY,
                backtest_dataset_id integer NOT NULL,
                dataset_manifest_hash varchar(64) NOT NULL,
                indicator_kind varchar(20) NOT NULL,
                period integer NOT NULL,
                formula_version varchar(100) NOT NULL,
                content_hash varchar(64) NOT NULL,
                status varchar(20) NOT NULL
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE backtest_runs (
                id serial PRIMARY KEY,
                run_id varchar(80) NOT NULL,
                backtest_strategy_version_id integer NOT NULL,
                backtest_dataset_id integer,
                backtest_dataset_rs_run_id integer,
                dataset_id varchar(80),
                dataset_manifest_hash varchar(64),
                rs_formula_version varchar(100),
                rs_result_hash varchar(64),
                range_start date NOT NULL,
                range_end date NOT NULL,
                markets jsonb NOT NULL,
                status varchar(20) NOT NULL DEFAULT 'queued'
            )
        """)
        conn.exec_driver_sql("""
            INSERT INTO backtest_runs (
                run_id, backtest_strategy_version_id, range_start, range_end, markets
            ) VALUES ('pre-existing', 1, '2024-01-02', '2024-01-03', '["KOSPI"]'::jsonb)
        """)
        try:
            yield conn
        finally:
            transaction.rollback()
    engine.dispose()


def test_revision_preserves_old_runs_and_enforces_dataset_bound_snapshot_pins(connection):
    spec = importlib.util.spec_from_file_location("t5_indicator_pin_migration", MIGRATION_PATH)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.op = Operations(MigrationContext.configure(connection))

    migration.upgrade()

    columns = {column["name"] for column in inspect(connection).get_columns("backtest_runs")}
    assert {
        "volume_sma50_snapshot_id", "volume_sma50_snapshot_hash",
        "atr14_snapshot_id", "atr14_snapshot_hash",
    } <= columns
    assert connection.scalar(text(
        "SELECT volume_sma50_snapshot_id FROM backtest_runs WHERE run_id='pre-existing'"
    )) is None

    connection.execute(text("""
        INSERT INTO backtest_dataset_indicator_snapshots
        (id, backtest_dataset_id, dataset_manifest_hash, indicator_kind, period, formula_version, content_hash, status)
        VALUES (10, 42, :manifest, 'volume_sma', 50, 'volume-sma-v1', :content, 'complete')
    """), {"manifest": "a" * 64, "content": "b" * 64})
    connection.execute(text("""
        INSERT INTO backtest_runs (
            run_id, backtest_strategy_version_id, backtest_dataset_id, dataset_id, dataset_manifest_hash,
            rs_formula_version, rs_result_hash, range_start, range_end, markets, status,
            volume_sma50_snapshot_id, volume_sma50_snapshot_hash
        ) VALUES (
            'pinned', 2, 42, 'dataset-42', :manifest, 'rs-v1', :rs_hash,
            '2024-01-02', '2024-01-03', '["KOSPI"]'::jsonb, 'queued', 10, :content
        )
    """), {"manifest": "a" * 64, "rs_hash": "c" * 64, "content": "b" * 64})

    with pytest.raises(SQLAlchemyError, match="backtest run inputs are immutable"):
        with connection.begin_nested():
            connection.execute(text("""
                UPDATE backtest_runs SET volume_sma50_snapshot_hash = :hash, status = 'running'
                WHERE run_id = 'pinned'
            """), {"hash": "d" * 64})

    with pytest.raises(SQLAlchemyError, match="volume_sma50 snapshot does not match"):
        with connection.begin_nested():
            connection.execute(text("""
                INSERT INTO backtest_runs (
                    run_id, backtest_strategy_version_id, backtest_dataset_id, dataset_id, dataset_manifest_hash,
                    rs_formula_version, rs_result_hash, range_start, range_end, markets, status,
                    volume_sma50_snapshot_id, volume_sma50_snapshot_hash
                ) VALUES (
                    'wrong-dataset', 3, 99, 'dataset-99', :manifest, 'rs-v1', :rs_hash,
                    '2024-01-02', '2024-01-03', '["KOSPI"]'::jsonb, 'queued', 10, :content
                )
            """), {"manifest": "a" * 64, "rs_hash": "c" * 64, "content": "b" * 64})
