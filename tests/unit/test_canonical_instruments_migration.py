"""Regression tests for the canonical-instruments Alembic migration."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock


def test_upgrade_preserves_tables_precreated_by_application_startup(monkeypatch):
    """A legacy ``create_all`` startup must not make the migration fail."""
    migration_path = (
        Path(__file__).parents[2]
        / "alembic/versions/d0e1f2a3b4c5_add_canonical_instruments.py"
    )
    spec = importlib.util.spec_from_file_location("canonical_instruments_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    inspector = Mock()
    inspector.has_table.return_value = True

    monkeypatch.setattr(migration.op, "get_bind", Mock(return_value=object()))
    monkeypatch.setattr(migration.sa, "inspect", Mock(return_value=inspector))
    create_table = Mock()
    monkeypatch.setattr(migration.op, "create_table", create_table)
    monkeypatch.setattr(migration.op, "create_index", Mock())
    monkeypatch.setattr(migration.op, "add_column", Mock())
    monkeypatch.setattr(migration.op, "create_foreign_key", Mock())

    migration.upgrade()

    assert create_table.call_count == 0
    assert inspector.has_table.call_args_list == [
        (("instruments",),),
        (("provider_symbols",),),
        (("universe_exclusions",),),
    ]


def test_reconciliation_run_upgrade_preserves_precreated_table(monkeypatch):
    """The reconciliation-run migration must also tolerate ``create_all``."""
    migration_path = (
        Path(__file__).parents[2]
        / "alembic/versions/e1f2a3b4c5d6_add_universe_reconciliation_runs.py"
    )
    spec = importlib.util.spec_from_file_location("reconciliation_runs_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    inspector = Mock()
    inspector.has_table.return_value = True

    monkeypatch.setattr(migration.op, "get_bind", Mock(return_value=object()), raising=False)
    monkeypatch.setattr(migration.sa, "inspect", Mock(return_value=inspector))
    create_table = Mock()
    monkeypatch.setattr(migration.op, "create_table", create_table)
    monkeypatch.setattr(migration.op, "create_index", Mock())

    migration.upgrade()

    assert create_table.call_count == 0
    inspector.has_table.assert_called_once_with("universe_reconciliation_runs")
