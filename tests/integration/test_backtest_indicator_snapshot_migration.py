"""Append-only migration and immutability checks on isolated PostgreSQL schemas."""

import importlib.util
import os
from pathlib import Path
from datetime import date
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError


VERSIONS = Path(__file__).parents[2] / "alembic" / "versions"
REVISION = "a8b9c0d1e2f3"


def migration(connection):
    path = next(VERSIONS.glob(REVISION + "_*.py"))
    spec = importlib.util.spec_from_file_location(REVISION, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    return module


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
        schema = "backtest_indicator_test_" + uuid4().hex
        conn.exec_driver_sql(f"CREATE SCHEMA {schema}")
        conn.exec_driver_sql(f"SET LOCAL search_path TO {schema}")
        _create_base_tables(conn)
        try:
            yield conn
        finally:
            transaction.rollback()
    engine.dispose()


def _create_base_tables(conn):
    for statement in (
        "CREATE TABLE backtest_datasets (id integer PRIMARY KEY, dataset_id varchar(80), final_manifest_hash varchar(64))",
        "CREATE TABLE backtest_dataset_prices (id integer PRIMARY KEY, backtest_dataset_id integer, trade_date date, close numeric)",
        "CREATE TABLE backtest_runs (id integer PRIMARY KEY, dataset_id varchar(80), result_hash varchar(64), status varchar(20))",
        "CREATE TABLE instruments (id integer PRIMARY KEY)",
        "CREATE TABLE indicator_series (id integer PRIMARY KEY)",
        "CREATE TABLE indicator_generations (id integer PRIMARY KEY, series_id integer NOT NULL, UNIQUE(id, series_id))",
        "CREATE TABLE indicator_calculation_runs (id integer PRIMARY KEY, generation_id integer NOT NULL, UNIQUE(id, generation_id))",
        "CREATE TABLE indicator_input_policies (id integer PRIMARY KEY)",
        "CREATE TABLE indicator_values (id integer PRIMARY KEY)",
        "CREATE TABLE indicator_run_inputs (id integer PRIMARY KEY)",
        "CREATE TABLE indicator_input_evidence (id integer PRIMARY KEY)",
        "CREATE TABLE symbols (id integer PRIMARY KEY)",
        "CREATE TABLE price_observations (id integer PRIMARY KEY)",
        "CREATE TABLE price_observation_identity_snapshots (id integer PRIMARY KEY)",
        "CREATE TABLE provider_symbols (id integer PRIMARY KEY)",
    ):
        conn.exec_driver_sql(statement)
    conn.exec_driver_sql("INSERT INTO backtest_datasets VALUES (1, 'old-dataset', 'a')")
    conn.exec_driver_sql("INSERT INTO backtest_dataset_prices VALUES (1, 1, '2024-01-02', 100)")
    conn.exec_driver_sql("INSERT INTO backtest_runs VALUES (1, 'old-dataset', 'b', 'completed')")


def rejected(connection, statement, params=None):
    savepoint = connection.begin_nested()
    with pytest.raises(DBAPIError):
        connection.execute(text(statement), params or {})
    savepoint.rollback()


def test_migration_upgrades_existing_dataset_rows_and_empty_downgrade_is_reversible(connection):
    module = migration(connection)
    module.upgrade()

    assert connection.execute(text("SELECT dataset_id, final_manifest_hash FROM backtest_datasets WHERE id=1")).one() == (
        "old-dataset", "a",
    )
    assert connection.execute(text("SELECT backtest_dataset_id, trade_date, close FROM backtest_dataset_prices WHERE id=1")).one() == (
        1, date(2024, 1, 2), 100,
    )
    assert connection.execute(text("SELECT dataset_id, result_hash, status FROM backtest_runs WHERE id=1")).one() == (
        "old-dataset", "b", "completed",
    )
    assert inspect(connection).has_table("backtest_dataset_indicator_snapshots")
    assert inspect(connection).has_table("backtest_dataset_indicator_snapshot_sources")
    assert inspect(connection).has_table("backtest_dataset_indicator_snapshot_rows")

    module.downgrade()
    assert not inspect(connection).has_table("backtest_dataset_indicator_snapshots")
    module.upgrade()


def test_postgres_rejects_mutation_of_completed_snapshot_and_members(connection):
    module = migration(connection)
    module.upgrade()
    for statement in (
        "INSERT INTO instruments VALUES (1)",
        "INSERT INTO indicator_series VALUES (1)",
        "INSERT INTO indicator_generations VALUES (1,1)",
        "INSERT INTO indicator_calculation_runs VALUES (1,1)",
        "INSERT INTO indicator_input_policies VALUES (1)",
        "INSERT INTO indicator_values VALUES (1)",
        "INSERT INTO indicator_run_inputs VALUES (1)",
        "INSERT INTO indicator_input_evidence VALUES (1)",
        "INSERT INTO symbols VALUES (1)",
        "INSERT INTO price_observations VALUES (1)",
        "INSERT INTO price_observation_identity_snapshots VALUES (1)",
        "INSERT INTO provider_symbols VALUES (1)",
    ):
        connection.exec_driver_sql(statement)
    snapshot_id = connection.execute(text("""
        INSERT INTO backtest_dataset_indicator_snapshots
            (snapshot_key, backtest_dataset_id, dataset_id, dataset_manifest_hash,
             indicator_kind, period, formula_version, source_policy_fingerprint,
             range_start, range_end, source_count, row_count, input_hash, result_hash, content_hash)
        VALUES ('s1', 1, 'old-dataset', :dataset_hash, 'volume_sma', 50, 'volume-sma-v1',
                :policy_hash, '2024-01-02', '2024-01-02', 1, 1, :input_hash, :result_hash, :content_hash)
        RETURNING id
    """), {
        "dataset_hash": "a" * 64, "policy_hash": "b" * 64,
        "input_hash": "c" * 64, "result_hash": "d" * 64, "content_hash": "e" * 64,
    }).scalar_one()
    connection.execute(text("""
        INSERT INTO backtest_dataset_indicator_snapshot_sources
            (snapshot_id, instrument_id, indicator_series_id, generation_id, calculation_run_id,
             input_policy_id, source_policy_fingerprint, input_hash, result_hash)
        VALUES (:snapshot, 1, 1, 1, 1, 1, :policy_hash, :input_hash, :result_hash)
    """), {"snapshot": snapshot_id, "policy_hash": "b" * 64,
           "input_hash": "c" * 64, "result_hash": "d" * 64})
    source_id = connection.execute(text(
        "SELECT id FROM backtest_dataset_indicator_snapshot_sources WHERE snapshot_id=:snapshot"
    ), {"snapshot": snapshot_id}).scalar_one()
    connection.execute(text("""
        INSERT INTO backtest_dataset_indicator_snapshot_rows
            (snapshot_id, source_id, instrument_id, trade_date, source_value_id, source_run_input_id,
             source_evidence_id, value, status, available_observations, input_prefix_hash,
             source_evidence_key, source_symbol_id, price_observation_id, identity_snapshot_id,
             provider_symbol_mapping_id, mapping_status, resolver_version, resolved_at, provider,
             provider_symbol, adjustment_type, parser_version, observed_at, payload_hash,
             open, high, low, close, volume, correction_ids, validation_evidence, row_hash)
        VALUES (:snapshot, :source, 1, '2024-01-02', 1, 1, 1, 1000, 'available', 50,
                :prefix_hash, :evidence_hash, 1, 1, 1, 1, 'matched', 'resolver-v1', now(),
                'kiwoom', 'A005930', '1', 'parser-v1', now(), :payload_hash,
                100, 110, 90, 105, 1000, '[]', '[]', :row_hash)
    """), {"snapshot": snapshot_id, "source": source_id,
           "prefix_hash": "1" * 64, "evidence_hash": "f" * 64,
           "payload_hash": "2" * 64, "row_hash": "3" * 64})
    connection.execute(text("""
        UPDATE backtest_dataset_indicator_snapshots SET status='complete', completed_at=now() WHERE id=:id
    """), {"id": snapshot_id})

    rejected(connection, "UPDATE backtest_dataset_indicator_snapshots SET content_hash=:hash WHERE id=:id",
             {"hash": "4" * 64, "id": snapshot_id})
    rejected(connection, "DELETE FROM backtest_dataset_indicator_snapshots WHERE id=:id", {"id": snapshot_id})
    rejected(connection, "UPDATE backtest_dataset_indicator_snapshot_sources SET input_hash=:hash WHERE snapshot_id=:id",
             {"hash": "4" * 64, "id": snapshot_id})
    rejected(connection, "DELETE FROM backtest_dataset_indicator_snapshot_rows WHERE snapshot_id=:id",
             {"id": snapshot_id})
    with pytest.raises(RuntimeError, match="cannot downgrade immutable"):
        module.downgrade()
    assert connection.execute(text(
        "SELECT content_hash FROM backtest_dataset_indicator_snapshots WHERE id=:id"
    ), {"id": snapshot_id}).scalar_one() == "e" * 64
