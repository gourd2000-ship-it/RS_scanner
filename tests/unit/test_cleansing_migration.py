"""기존 데이터셋 테이블을 지우지 않고 품질 필드가 추가되는지 검사한다."""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def test_ohlcv_migration_keeps_existing_rows_and_adds_nullable_columns():
    engine = create_engine("sqlite://")
    migration_path = Path(__file__).parents[2] / "alembic/versions/p9c0d1e2f3a4_dataset_ohlcv_quality.py"
    spec = importlib.util.spec_from_file_location("ohlcv_quality_migration", migration_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE backtest_dataset_memberships (id INTEGER PRIMARY KEY, code TEXT)")
        connection.exec_driver_sql("CREATE TABLE backtest_dataset_prices (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO backtest_dataset_memberships(id, code) VALUES (1, '000001')")
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        assert connection.exec_driver_sql("SELECT code FROM backtest_dataset_memberships WHERE id=1").scalar() == "000001"
        member_columns = {column["name"] for column in inspect(connection).get_columns("backtest_dataset_memberships")}
        price_columns = {column["name"] for column in inspect(connection).get_columns("backtest_dataset_prices")}
        assert {"name", "quality_status", "quality_reason", "quality_evidence"} <= member_columns
        assert "correction_ids" in price_columns
        module.upgrade()
