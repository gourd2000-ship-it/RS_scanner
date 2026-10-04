"""Schema-level regression tests for the append-only EMA migration."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError


def _migration_module():
    path = Path(__file__).parents[2] / "alembic/versions/w4a5b6c7d8e9_add_indicator_ema_lineage_storage.py"
    spec = importlib.util.spec_from_file_location("indicator_ema_storage_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_indicator_migration_creates_lineage_schema_and_constraints():
    engine = create_engine("sqlite://")
    migration = _migration_module()
    with engine.begin() as connection:
        # The migration references historical source tables but does not alter
        # them.  Minimal parents let the migration exercise real DDL on SQLite.
        for table in ("instruments", "symbols", "provider_symbols", "price_observations"):
            connection.exec_driver_sql(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        inspector = inspect(connection)
        assert {
            "price_observation_identity_snapshots", "indicator_series", "indicator_generations",
            "indicator_calculation_runs", "indicator_input_snapshots", "indicator_values",
        } <= set(inspector.get_table_names())
        assert {constraint["name"] for constraint in inspector.get_check_constraints("indicator_values")} >= {
            "ck_indicator_values_period", "ck_indicator_values_status", "ck_indicator_values_status_shape",
        }
        assert {constraint["name"] for constraint in inspector.get_check_constraints("indicator_calculation_runs")} >= {
            "ck_indicator_runs_kind", "ck_indicator_runs_status", "ck_indicator_runs_completed_evidence",
            "ck_indicator_runs_input_count", "ck_indicator_runs_result_count", "ck_indicator_runs_excluded_count",
        }
        assert {constraint["name"] for constraint in inspector.get_check_constraints("indicator_generations")} >= {
            "ck_indicator_generations_status", "ck_indicator_generations_positive_number",
        }
        assert {
            foreign_key["name"] for foreign_key in inspector.get_foreign_keys("indicator_input_snapshots")
        } >= {
            "fk_indicator_input_snapshot_run_generation",
            "fk_indicator_input_snapshot_identity_observation",
        }
        assert any(index["name"] == "uq_indicator_generations_one_current" for index in inspector.get_indexes("indicator_generations"))
        assert any(index["name"] == "uq_indicator_runs_one_running_per_series" for index in inspector.get_indexes("indicator_calculation_runs"))

        connection.exec_driver_sql("INSERT INTO instruments (id) VALUES (1)")
        connection.exec_driver_sql(
            "INSERT INTO indicator_series (id, instrument_id, source_provider, adjustment_policy, allowed_parser_versions, observation_cutoff) "
            "VALUES (1, 1, 'kiwoom', '1', '[\"kiwoom-v2\"]', '2024-01-01 00:00:00')"
        )
        connection.exec_driver_sql("INSERT INTO indicator_generations (id, series_id, generation, status) VALUES (1, 1, 1, 'building')")
        connection.exec_driver_sql(
            "INSERT INTO indicator_calculation_runs (id, generation_id, series_id, run_kind, status, input_cutoff) "
            "VALUES (1, 1, 1, 'backfill', 'running', '2024-01-01 00:00:00')"
        )
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "INSERT INTO indicator_values (calculation_run_id, generation_id, period, trade_date, value, status, available_observations, input_prefix_hash) "
                "VALUES (1, 1, 7, '2024-01-02', 100, 'available', 7, 'a')"
            )


def test_postgresql_migration_installs_completed_run_immutability_triggers():
    """Keep the PostgreSQL-only durability requirement visible in migration tests."""
    source = (Path(__file__).parents[2] / "alembic/versions/w4a5b6c7d8e9_add_indicator_ema_lineage_storage.py").read_text()
    assert "trg_indicator_runs_completed_immutable" in source
    assert "trg_indicator_input_snapshots_completed_immutable" in source
    assert "trg_indicator_values_completed_immutable" in source
    assert "trg_price_observation_identity_snapshots_immutable" in source
    assert "OLD.calculation_run_id, NEW.calculation_run_id" in source
