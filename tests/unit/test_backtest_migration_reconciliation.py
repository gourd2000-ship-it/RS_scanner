"""혼합 스키마에서 backtest migration이 이미 있는 테이블을 재생성하지 않는다."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock


def _load_migration(filename: str):
    path = Path(__file__).parents[2] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dataset_migration_skips_tables_that_were_created_before_alembic_revision():
    migration = _load_migration("l5e6f7a8b9c0_backtest_datasets.py")
    inspector = Mock()
    inspector.has_table.return_value = True
    create_table = Mock()
    create_index = Mock()
    monkeypatch = __import__("pytest").MonkeyPatch()
    monkeypatch.setattr(migration.op, "get_bind", Mock(return_value=object()), raising=False)
    monkeypatch.setattr(migration.sa, "inspect", Mock(return_value=inspector))
    monkeypatch.setattr(migration.op, "create_table", create_table)
    monkeypatch.setattr(migration.op, "create_index", create_index)
    try:
        migration.upgrade()
    finally:
        monkeypatch.undo()

    create_table.assert_not_called()


def test_rs_migration_adds_missing_column_but_skips_existing_rs_tables():
    migration = _load_migration("m6f7a8b9c0d1_backtest_dataset_rs.py")
    inspector = Mock()
    inspector.has_table.return_value = True
    inspector.get_columns.return_value = [{"name": "manifest_hash"}]
    inspector.get_indexes.return_value = []
    create_table = Mock()
    add_column = Mock()
    create_index = Mock()
    monkeypatch = __import__("pytest").MonkeyPatch()
    monkeypatch.setattr(migration.op, "get_bind", Mock(return_value=object()), raising=False)
    monkeypatch.setattr(migration.sa, "inspect", Mock(return_value=inspector))
    monkeypatch.setattr(migration.op, "create_table", create_table)
    monkeypatch.setattr(migration.op, "add_column", add_column)
    monkeypatch.setattr(migration.op, "create_index", create_index)
    try:
        migration.upgrade()
    finally:
        monkeypatch.undo()

    add_column.assert_called_once()
    create_table.assert_not_called()
