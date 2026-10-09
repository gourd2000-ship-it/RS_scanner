"""Pin MA50/ATR14 values and evidence to complete backtest datasets.

Revision ID: a8b9c0d1e2f3
Revises: z7d8e9f0a1b2
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "z7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "backtest_dataset_indicator_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_key", sa.String(64), nullable=False),
        sa.Column("backtest_dataset_id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.String(80), nullable=False),
        sa.Column("dataset_manifest_hash", sa.String(64), nullable=False),
        sa.Column("indicator_kind", sa.String(20), nullable=False),
        sa.Column("period", sa.Integer(), nullable=False),
        sa.Column("formula_version", sa.String(100), nullable=False),
        sa.Column("source_policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("range_start", sa.Date(), nullable=False),
        sa.Column("range_end", sa.Date(), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="building"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["backtest_dataset_id"], ["backtest_datasets.id"], name="fk_backtest_indicator_snapshot_dataset"),
        sa.UniqueConstraint("snapshot_key", name="uq_backtest_indicator_snapshot_key"),
        sa.CheckConstraint("indicator_kind IN ('volume_sma', 'atr')", name="ck_backtest_indicator_snapshot_kind"),
        sa.CheckConstraint(
            "(indicator_kind = 'volume_sma' AND period = 50 AND formula_version = 'volume-sma-v1') OR "
            "(indicator_kind = 'atr' AND period = 14 AND formula_version = 'wilder-atr-14-v1')",
            name="ck_backtest_indicator_snapshot_definition",
        ),
        sa.CheckConstraint("range_start <= range_end", name="ck_backtest_indicator_snapshot_range"),
        sa.CheckConstraint("status IN ('building', 'complete')", name="ck_backtest_indicator_snapshot_status"),
        sa.CheckConstraint("source_count > 0 AND row_count > 0", name="ck_backtest_indicator_snapshot_counts"),
        sa.CheckConstraint("status = 'building' OR completed_at IS NOT NULL", name="ck_backtest_indicator_snapshot_completed_at"),
        sa.CheckConstraint(
            "length(source_policy_fingerprint) = 64 AND length(input_hash) = 64 "
            "AND length(result_hash) = 64 AND length(content_hash) = 64",
            name="ck_backtest_indicator_snapshot_hashes",
        ),
    )
    op.create_index(
        "ix_backtest_indicator_snapshot_dataset",
        "backtest_dataset_indicator_snapshots",
        ["backtest_dataset_id", "indicator_kind", "period"],
    )

    op.create_table(
        "backtest_dataset_indicator_snapshot_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("indicator_series_id", sa.Integer(), nullable=False),
        sa.Column("generation_id", sa.Integer(), nullable=False),
        sa.Column("calculation_run_id", sa.Integer(), nullable=False),
        sa.Column("input_policy_id", sa.Integer(), nullable=False),
        sa.Column("source_policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["backtest_dataset_indicator_snapshots.id"], name="fk_backtest_indicator_snapshot_source_snapshot"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], name="fk_backtest_indicator_snapshot_source_instrument"),
        sa.ForeignKeyConstraint(["indicator_series_id"], ["indicator_series.id"], name="fk_backtest_indicator_snapshot_source_series"),
        sa.ForeignKeyConstraint(["generation_id", "indicator_series_id"], ["indicator_generations.id", "indicator_generations.series_id"], name="fk_backtest_indicator_snapshot_source_generation_series"),
        sa.ForeignKeyConstraint(["calculation_run_id", "generation_id"], ["indicator_calculation_runs.id", "indicator_calculation_runs.generation_id"], name="fk_backtest_indicator_snapshot_source_run_generation"),
        sa.ForeignKeyConstraint(["input_policy_id"], ["indicator_input_policies.id"], name="fk_backtest_indicator_snapshot_source_policy"),
        sa.UniqueConstraint("snapshot_id", "instrument_id", name="uq_backtest_indicator_snapshot_source_instrument"),
        sa.UniqueConstraint("id", "snapshot_id", "instrument_id", name="uq_backtest_indicator_snapshot_source_identity"),
        sa.CheckConstraint(
            "length(source_policy_fingerprint) = 64 AND length(input_hash) = 64 AND length(result_hash) = 64",
            name="ck_backtest_indicator_snapshot_source_hashes",
        ),
    )
    op.create_index(
        "ix_backtest_indicator_snapshot_source_run",
        "backtest_dataset_indicator_snapshot_sources",
        ["calculation_run_id"],
    )

    op.create_table(
        "backtest_dataset_indicator_snapshot_rows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("source_value_id", sa.Integer(), nullable=False),
        sa.Column("source_run_input_id", sa.Integer(), nullable=False),
        sa.Column("source_evidence_id", sa.Integer(), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("reason_code", sa.String(100), nullable=True),
        sa.Column("available_observations", sa.Integer(), nullable=False),
        sa.Column("input_prefix_hash", sa.String(64), nullable=False),
        sa.Column("source_evidence_key", sa.String(64), nullable=False),
        sa.Column("source_symbol_id", sa.Integer(), nullable=False),
        sa.Column("price_observation_id", sa.Integer(), nullable=False),
        sa.Column("identity_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("provider_symbol_mapping_id", sa.Integer(), nullable=False),
        sa.Column("mapping_status", sa.String(30), nullable=False),
        sa.Column("mapping_valid_from", sa.Date(), nullable=True),
        sa.Column("mapping_valid_to", sa.Date(), nullable=True),
        sa.Column("resolver_version", sa.String(100), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("provider_symbol", sa.String(50), nullable=False),
        sa.Column("adjustment_type", sa.String(100), nullable=False),
        sa.Column("parser_version", sa.String(100), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("open", sa.Numeric(), nullable=False),
        sa.Column("high", sa.Numeric(), nullable=False),
        sa.Column("low", sa.Numeric(), nullable=False),
        sa.Column("close", sa.Numeric(), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("correction_ids", sa.JSON(), nullable=False),
        sa.Column("validation_evidence", sa.JSON(), nullable=False),
        sa.Column("row_hash", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["backtest_dataset_indicator_snapshots.id"], name="fk_backtest_indicator_snapshot_row_snapshot"),
        sa.ForeignKeyConstraint(["source_id", "snapshot_id", "instrument_id"], ["backtest_dataset_indicator_snapshot_sources.id", "backtest_dataset_indicator_snapshot_sources.snapshot_id", "backtest_dataset_indicator_snapshot_sources.instrument_id"], name="fk_backtest_indicator_snapshot_row_source"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], name="fk_backtest_indicator_snapshot_row_instrument"),
        sa.ForeignKeyConstraint(["source_value_id"], ["indicator_values.id"], name="fk_backtest_indicator_snapshot_row_value"),
        sa.ForeignKeyConstraint(["source_run_input_id"], ["indicator_run_inputs.id"], name="fk_backtest_indicator_snapshot_row_run_input"),
        sa.ForeignKeyConstraint(["source_evidence_id"], ["indicator_input_evidence.id"], name="fk_backtest_indicator_snapshot_row_evidence"),
        sa.ForeignKeyConstraint(["source_symbol_id"], ["symbols.id"], name="fk_backtest_indicator_snapshot_row_symbol"),
        sa.ForeignKeyConstraint(["price_observation_id"], ["price_observations.id"], name="fk_backtest_indicator_snapshot_row_observation"),
        sa.ForeignKeyConstraint(["identity_snapshot_id"], ["price_observation_identity_snapshots.id"], name="fk_backtest_indicator_snapshot_row_identity"),
        sa.ForeignKeyConstraint(["provider_symbol_mapping_id"], ["provider_symbols.id"], name="fk_backtest_indicator_snapshot_row_mapping"),
        sa.UniqueConstraint("snapshot_id", "instrument_id", "trade_date", name="uq_backtest_indicator_snapshot_value_date"),
        sa.CheckConstraint("status IN ('available', 'warming_up', 'data_unavailable')", name="ck_backtest_indicator_snapshot_row_status"),
        sa.CheckConstraint(
            "(status = 'available' AND value IS NOT NULL AND reason_code IS NULL) OR "
            "(status = 'warming_up' AND value IS NULL AND reason_code = 'warming_up') OR "
            "(status = 'data_unavailable' AND value IS NULL AND reason_code IS NOT NULL AND reason_code <> 'warming_up')",
            name="ck_backtest_indicator_snapshot_row_value_shape",
        ),
        sa.CheckConstraint("available_observations >= 0", name="ck_backtest_indicator_snapshot_row_observation_count"),
        sa.CheckConstraint("mapping_status = 'matched'", name="ck_backtest_indicator_snapshot_row_matched_identity"),
        sa.CheckConstraint(
            "mapping_valid_to IS NULL OR mapping_valid_from IS NULL OR mapping_valid_from < mapping_valid_to",
            name="ck_backtest_indicator_snapshot_row_mapping_range",
        ),
        sa.CheckConstraint(
            "open > 0 AND high > 0 AND low > 0 AND close > 0 AND volume >= 0 "
            "AND high >= low AND high >= open AND high >= close AND low <= open AND low <= close",
            name="ck_backtest_indicator_snapshot_row_valid_ohlcv",
        ),
        sa.CheckConstraint(
            "length(input_prefix_hash) = 64 AND length(source_evidence_key) = 64 AND length(row_hash) = 64",
            name="ck_backtest_indicator_snapshot_row_hashes",
        ),
    )
    op.create_index(
        "ix_backtest_indicator_snapshot_row_lookup",
        "backtest_dataset_indicator_snapshot_rows",
        ["snapshot_id", "trade_date", "instrument_id"],
    )
    op.create_index(
        "ix_backtest_indicator_snapshot_row_source_value",
        "backtest_dataset_indicator_snapshot_rows",
        ["source_value_id"],
    )
    if op.get_bind().dialect.name == "postgresql":
        _postgresql_immutability()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "LOCK TABLE backtest_dataset_indicator_snapshots, "
            "backtest_dataset_indicator_snapshot_sources, "
            "backtest_dataset_indicator_snapshot_rows IN ACCESS EXCLUSIVE MODE"
        )
    count = bind.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM backtest_dataset_indicator_snapshots) "
        "OR EXISTS (SELECT 1 FROM backtest_dataset_indicator_snapshot_sources) "
        "OR EXISTS (SELECT 1 FROM backtest_dataset_indicator_snapshot_rows)"
    )).scalar()
    if count:
        raise RuntimeError("cannot downgrade immutable backtest indicator snapshots; preserve them and roll forward")
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_backtest_indicator_snapshot_guard ON backtest_dataset_indicator_snapshots")
        op.execute("DROP TRIGGER IF EXISTS trg_backtest_indicator_snapshot_source_guard ON backtest_dataset_indicator_snapshot_sources")
        op.execute("DROP TRIGGER IF EXISTS trg_backtest_indicator_snapshot_row_guard ON backtest_dataset_indicator_snapshot_rows")
        op.execute("DROP FUNCTION IF EXISTS backtest_indicator_snapshot_guard()")
        op.execute("DROP FUNCTION IF EXISTS backtest_indicator_snapshot_child_guard()")
    op.drop_table("backtest_dataset_indicator_snapshot_rows")
    op.drop_index("ix_backtest_indicator_snapshot_source_run", table_name="backtest_dataset_indicator_snapshot_sources")
    op.drop_table("backtest_dataset_indicator_snapshot_sources")
    op.drop_index("ix_backtest_indicator_snapshot_dataset", table_name="backtest_dataset_indicator_snapshots")
    op.drop_table("backtest_dataset_indicator_snapshots")


def _postgresql_immutability() -> None:
    op.execute("""
        CREATE FUNCTION backtest_indicator_snapshot_guard() RETURNS trigger AS $$
        DECLARE source_total integer; row_total integer;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'backtest indicator snapshots are immutable';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'building' OR NEW.completed_at IS NOT NULL THEN
                    RAISE EXCEPTION 'backtest indicator snapshot must be created as building';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.status <> 'building' OR NEW.status <> 'complete'
               OR (to_jsonb(NEW) - ARRAY['status', 'completed_at'])
                  IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status', 'completed_at'])
               OR NEW.completed_at IS NULL THEN
                RAISE EXCEPTION 'backtest indicator snapshot only permits one building-to-complete transition';
            END IF;
            SELECT count(*) INTO source_total
            FROM backtest_dataset_indicator_snapshot_sources WHERE snapshot_id = OLD.id;
            SELECT count(*) INTO row_total
            FROM backtest_dataset_indicator_snapshot_rows WHERE snapshot_id = OLD.id;
            IF source_total <> OLD.source_count OR row_total <> OLD.row_count THEN
                RAISE EXCEPTION 'backtest indicator snapshot is incomplete';
            END IF;
            IF EXISTS (
                SELECT 1 FROM backtest_dataset_indicator_snapshot_sources
                WHERE snapshot_id = OLD.id
                  AND source_policy_fingerprint <> OLD.source_policy_fingerprint
            ) THEN
                RAISE EXCEPTION 'backtest indicator snapshot mixes source policies';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE FUNCTION backtest_indicator_snapshot_child_guard() RETURNS trigger AS $$
        DECLARE parent_status text;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'backtest indicator snapshot members are immutable';
            END IF;
            SELECT status INTO parent_status
            FROM backtest_dataset_indicator_snapshots
            WHERE id = NEW.snapshot_id FOR KEY SHARE;
            IF parent_status IS DISTINCT FROM 'building' THEN
                RAISE EXCEPTION 'backtest indicator snapshot members can only be inserted while building';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_backtest_indicator_snapshot_guard
        BEFORE INSERT OR UPDATE OR DELETE ON backtest_dataset_indicator_snapshots
        FOR EACH ROW EXECUTE FUNCTION backtest_indicator_snapshot_guard()
    """)
    op.execute("""
        CREATE TRIGGER trg_backtest_indicator_snapshot_source_guard
        BEFORE INSERT OR UPDATE OR DELETE ON backtest_dataset_indicator_snapshot_sources
        FOR EACH ROW EXECUTE FUNCTION backtest_indicator_snapshot_child_guard()
    """)
    op.execute("""
        CREATE TRIGGER trg_backtest_indicator_snapshot_row_guard
        BEFORE INSERT OR UPDATE OR DELETE ON backtest_dataset_indicator_snapshot_rows
        FOR EACH ROW EXECUTE FUNCTION backtest_indicator_snapshot_child_guard()
    """)
