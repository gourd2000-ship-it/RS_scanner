"""Repair a pre-Alembic indicator schema drift without touching EMA history.

This is only for the state where an older development ``create_all`` call
created the three shared-input tables before the corresponding Alembic
revision.  The script performs no change unless ``--apply`` is supplied.
It refuses every other revision, non-empty shared table, partial migration, or
external foreign-key dependency.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, Engine, inspect, text

if __package__ in (None, ""):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import engine

PRE_COMMON_REVISION = "x5b6c7d8e9f0"
_SHARED_TABLES = (
    "indicator_run_inputs",
    "indicator_input_evidence",
    "indicator_input_policies",
)
_REQUIRED_COLUMNS = {
    "indicator_input_policies": {
        "id", "version", "provider", "adjustment_type", "allowed_parser_versions",
        "observation_cutoff", "selector_version", "validation_version",
        "correction_version", "fingerprint", "created_at",
    },
    "indicator_input_evidence": {
        "id", "input_policy_id", "evidence_key", "trade_date", "instrument_id",
        "source_symbol_id", "price_observation_id", "price_observation_identity_snapshot_id",
        "provider_symbol_mapping_id", "provider", "provider_symbol", "adjustment_type",
        "parser_version", "close", "volume", "observed_at", "payload_hash",
        "mapping_status", "mapping_valid_from", "mapping_valid_to", "resolver_version",
        "resolved_at", "correction_ids", "validation_evidence", "input_status",
        "reason_code", "created_at",
    },
    "indicator_run_inputs": {
        "id", "calculation_run_id", "evidence_id", "ordinal", "prefix_hash", "created_at",
    },
}
_LEGACY_COLUMNS = {
    "indicator_series": "input_policy_id",
    "indicator_values": "indicator_kind",
}


def _revision(connection: Connection) -> str | None:
    if not inspect(connection).has_table("alembic_version"):
        return None
    return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()


def _column_names(connection: Connection, table: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table)}


def _row_count(connection: Connection, table: str) -> int:
    # The table names are fixed module constants, never user input.
    return int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


def _incoming_dependencies(connection: Connection) -> list[dict[str, str]]:
    rows = connection.execute(text("""
        SELECT conrelid::regclass::text AS referencing_table,
               conname,
               confrelid::regclass::text AS referenced_table
        FROM pg_constraint
        WHERE contype = 'f'
          AND confrelid IN (
              'indicator_input_policies'::regclass,
              'indicator_input_evidence'::regclass,
              'indicator_run_inputs'::regclass
          )
        ORDER BY referencing_table, conname
    """)).mappings()
    return [dict(row) for row in rows]


def inspect_repair_state(connection: Connection) -> dict[str, Any]:
    """Return a reviewable state document; never modifies the database."""
    inspector = inspect(connection)
    present = {table: inspector.has_table(table) for table in _SHARED_TABLES}
    columns = {
        table: sorted(_column_names(connection, table)) if exists else []
        for table, exists in present.items()
    }
    counts = {
        table: _row_count(connection, table) if exists else None
        for table, exists in present.items()
    }
    legacy_columns = {
        table: sorted(_column_names(connection, table))
        for table in _LEGACY_COLUMNS
        if inspector.has_table(table)
    }
    revision = _revision(connection)
    dependencies = _incoming_dependencies(connection) if all(present.values()) else []

    problems: list[str] = []
    if revision != PRE_COMMON_REVISION:
        problems.append("unexpected_alembic_revision")
    if not all(present.values()):
        problems.append("shared_tables_missing")
    if any(count not in (0, None) for count in counts.values()):
        problems.append("shared_tables_not_empty")
    for table, required in _REQUIRED_COLUMNS.items():
        if present[table] and set(columns[table]) != required:
            problems.append(f"unexpected_columns:{table}")
    for table, added_by_migration in _LEGACY_COLUMNS.items():
        if added_by_migration in legacy_columns.get(table, set()):
            problems.append(f"migration_already_partially_applied:{table}")
    allowed_dependencies = {
        ("indicator_input_evidence", "indicator_input_evidence_input_policy_id_fkey", "indicator_input_policies"),
        ("indicator_run_inputs", "indicator_run_inputs_evidence_id_fkey", "indicator_input_evidence"),
    }
    observed_dependencies = {
        (row["referencing_table"], row["conname"], row["referenced_table"])
        for row in dependencies
    }
    if observed_dependencies != allowed_dependencies:
        problems.append("unexpected_shared_table_dependencies")

    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "expected_revision": PRE_COMMON_REVISION,
        "revision": revision,
        "shared_tables": {
            table: {"present": present[table], "row_count": counts[table], "columns": columns[table]}
            for table in _SHARED_TABLES
        },
        "legacy_columns": legacy_columns,
        "incoming_dependencies": dependencies,
        "eligible": not problems,
        "problems": problems,
    }


def reconcile(connection: Connection) -> dict[str, Any]:
    """Drop only verified empty pre-created shared tables in dependency order."""
    state = inspect_repair_state(connection)
    if not state["eligible"]:
        raise ValueError("indicator pre-migration repair refused: " + ", ".join(state["problems"]))
    for table in _SHARED_TABLES:
        connection.execute(text(f"DROP TABLE {table}"))
    state["dropped_tables"] = list(_SHARED_TABLES)
    state["eligible"] = True
    return state


def execute(target_engine: Engine, *, apply: bool) -> dict[str, Any]:
    if not apply:
        with target_engine.connect() as connection:
            return inspect_repair_state(connection)
    with target_engine.begin() as connection:
        return reconcile(connection)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="drop only the verified empty drift tables")
    args = parser.parse_args(argv)
    try:
        report = execute(engine, apply=args.apply)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
