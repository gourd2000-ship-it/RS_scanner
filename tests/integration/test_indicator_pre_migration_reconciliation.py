"""Regression coverage for safe recovery from pre-Alembic indicator tables."""
from sqlalchemy import text

from scripts.reconcile_indicator_pre_migration import (
    PRE_COMMON_REVISION,
    inspect_repair_state,
    reconcile,
)
from tests.integration.test_common_indicator_migration import connection as postgres_connection


def _create_precreated_shared_tables(conn):
    conn.execute(text("CREATE TABLE alembic_version (version_num varchar(32) NOT NULL)"))
    conn.execute(text("INSERT INTO alembic_version (version_num) VALUES (:revision)"), {"revision": PRE_COMMON_REVISION})
    conn.execute(text("""
        CREATE TABLE indicator_input_policies (
            id integer PRIMARY KEY, version varchar(100) NOT NULL, provider varchar(100) NOT NULL,
            adjustment_type varchar(100) NOT NULL, allowed_parser_versions jsonb NOT NULL,
            observation_cutoff timestamptz NOT NULL, selector_version varchar(100) NOT NULL,
            validation_version varchar(100) NOT NULL, correction_version varchar(100) NOT NULL,
            fingerprint varchar(64) NOT NULL, created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE TABLE indicator_input_evidence (
            id integer PRIMARY KEY, input_policy_id integer NOT NULL REFERENCES indicator_input_policies(id),
            evidence_key varchar(64) NOT NULL, trade_date date NOT NULL, instrument_id integer NOT NULL,
            source_symbol_id integer, price_observation_id integer,
            price_observation_identity_snapshot_id integer, provider_symbol_mapping_id integer,
            provider varchar(100) NOT NULL, provider_symbol varchar(50) NOT NULL,
            adjustment_type varchar(100), parser_version varchar(100), close numeric, volume integer,
            observed_at timestamptz, payload_hash varchar(64), mapping_status varchar(30),
            mapping_valid_from date, mapping_valid_to date, resolver_version varchar(100),
            resolved_at timestamptz, correction_ids json NOT NULL, validation_evidence json NOT NULL,
            input_status varchar(30) NOT NULL, reason_code varchar(100),
            created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE TABLE indicator_run_inputs (
            id integer PRIMARY KEY, calculation_run_id integer NOT NULL,
            evidence_id integer NOT NULL REFERENCES indicator_input_evidence(id), ordinal integer NOT NULL,
            prefix_hash varchar(64) NOT NULL, created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))


def test_reconcile_drops_only_empty_precreated_shared_tables(postgres_connection):
    conn = postgres_connection
    _create_precreated_shared_tables(conn)

    plan = inspect_repair_state(conn)
    assert plan["eligible"] is True
    assert [plan["shared_tables"][table]["row_count"] for table in plan["shared_tables"]] == [0, 0, 0]

    report = reconcile(conn)
    assert report["dropped_tables"] == [
        "indicator_run_inputs", "indicator_input_evidence", "indicator_input_policies"
    ]
    assert conn.execute(text("SELECT to_regclass('indicator_input_policies')")).scalar_one() is None
    assert conn.execute(text("SELECT count(*) FROM indicator_values")).scalar_one() == 0


def test_reconcile_refuses_any_persisted_shared_evidence(postgres_connection):
    conn = postgres_connection
    _create_precreated_shared_tables(conn)
    conn.execute(text("""
        INSERT INTO indicator_input_policies
        (id, version, provider, adjustment_type, allowed_parser_versions, observation_cutoff,
         selector_version, validation_version, correction_version, fingerprint)
        VALUES (1, 'validated-observation-ohlcv-v1', 'kiwoom', '1', '["v1"]', now(), 's', 'v', 'c', repeat('a', 64))
    """))

    plan = inspect_repair_state(conn)
    assert plan["eligible"] is False
    assert "shared_tables_not_empty" in plan["problems"]
