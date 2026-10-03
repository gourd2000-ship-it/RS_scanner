"""Add immutable EMA identity, input, and result lineage storage.

Revision ID: w4a5b6c7d8e9
Revises: v3a4b5c6d7e8
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "w4a5b6c7d8e9"
down_revision: str | Sequence[str] | None = "v3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "price_observation_identity_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("price_observation_id", sa.Integer(), sa.ForeignKey("price_observations.id"), nullable=False),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instruments.id"), nullable=True),
        sa.Column("provider_symbol_mapping_id", sa.Integer(), sa.ForeignKey("provider_symbols.id"), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("provider_symbol", sa.String(length=50), nullable=True),
        sa.Column("mapping_status", sa.String(length=30), nullable=True),
        sa.Column("mapping_valid_from", sa.Date(), nullable=True),
        sa.Column("mapping_valid_to", sa.Date(), nullable=True),
        sa.Column("resolver_version", sa.String(length=100), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("price_observation_id", name="uq_price_observation_identity_snapshot_observation"),
        sa.UniqueConstraint("id", "price_observation_id", name="uq_price_observation_identity_snapshot_id_observation"),
        sa.CheckConstraint(
            "mapping_status IS NULL OR mapping_status IN ('matched', 'unmatched', 'ambiguous', 'invalid_legacy')",
            name="ck_price_observation_identity_snapshot_mapping_status",
        ),
        sa.CheckConstraint(
            "mapping_valid_to IS NULL OR mapping_valid_from IS NULL OR mapping_valid_from < mapping_valid_to",
            name="ck_price_observation_identity_snapshot_mapping_range",
        ),
    )
    op.create_index("ix_price_observation_identity_snapshot_instrument", "price_observation_identity_snapshots", ["instrument_id"])
    op.create_index("ix_price_observation_identity_snapshot_mapping", "price_observation_identity_snapshots", ["provider_symbol_mapping_id"])

    op.create_table(
        "indicator_series",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("indicator_kind", sa.String(length=20), nullable=False, server_default="ema"),
        sa.Column("input_field", sa.String(length=20), nullable=False, server_default="close"),
        sa.Column("periods", sa.String(length=30), nullable=False, server_default="5,20,50,200"),
        sa.Column("input_policy_version", sa.String(length=100), nullable=False, server_default="validated-observation-close-v3"),
        sa.Column("formula_version", sa.String(length=100), nullable=False, server_default="ema-close-seed-v1"),
        sa.Column("source_provider", sa.String(length=100), nullable=False),
        sa.Column("adjustment_policy", sa.String(length=100), nullable=False),
        sa.Column("allowed_parser_versions", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("observation_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("indicator_kind = 'ema'", name="ck_indicator_series_kind_ema"),
        sa.CheckConstraint("input_field = 'close'", name="ck_indicator_series_input_close"),
        sa.CheckConstraint("periods = '5,20,50,200'", name="ck_indicator_series_periods"),
        sa.CheckConstraint(
            "input_policy_version = 'validated-observation-close-v3'",
            name="ck_indicator_series_input_policy_version",
        ),
        sa.CheckConstraint(
            "formula_version = 'ema-close-seed-v1'",
            name="ck_indicator_series_formula_version",
        ),
        sa.UniqueConstraint(
            "instrument_id", "indicator_kind", "input_field", "periods", "input_policy_version",
            "formula_version", "source_provider", "adjustment_policy", "allowed_parser_versions",
            "observation_cutoff", name="uq_indicator_series_policy",
        ),
    )
    op.create_index("ix_indicator_series_instrument", "indicator_series", ["instrument_id"])
    op.create_index("ix_indicator_series_instrument_policy", "indicator_series", ["instrument_id", "input_policy_version"])

    op.create_table(
        "indicator_generations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("series_id", sa.Integer(), sa.ForeignKey("indicator_series.id"), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("parent_generation_id", sa.Integer(), sa.ForeignKey("indicator_generations.id"), nullable=True),
        sa.Column("replacement_reason", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="building"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("series_id", "generation", name="uq_indicator_generation_number"),
        sa.UniqueConstraint("id", "series_id", name="uq_indicator_generation_id_series"),
        sa.CheckConstraint("status IN ('building', 'current', 'superseded', 'failed')", name="ck_indicator_generations_status"),
        sa.CheckConstraint("generation > 0", name="ck_indicator_generations_positive_number"),
    )
    op.create_index("ix_indicator_generations_series_status", "indicator_generations", ["series_id", "status"])
    op.create_index("ix_indicator_generations_parent_generation", "indicator_generations", ["parent_generation_id"])
    op.create_index(
        "uq_indicator_generations_one_current", "indicator_generations", ["series_id"], unique=True,
        postgresql_where=sa.text("status = 'current'"), sqlite_where=sa.text("status = 'current'"),
    )

    op.create_table(
        "indicator_calculation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("generation_id", sa.Integer(), nullable=False),
        sa.Column("series_id", sa.Integer(), nullable=False),
        sa.Column("run_kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("input_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("range_start", sa.Date(), nullable=True),
        sa.Column("range_end", sa.Date(), nullable=True),
        sa.Column("input_hash", sa.String(length=64), nullable=True),
        sa.Column("result_hash", sa.String(length=64), nullable=True),
        sa.Column("input_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("excluded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("id", "generation_id", name="uq_indicator_run_id_generation"),
        sa.ForeignKeyConstraint(
            ["generation_id", "series_id"], ["indicator_generations.id", "indicator_generations.series_id"],
            name="fk_indicator_run_generation_series",
        ),
        sa.CheckConstraint("run_kind IN ('backfill', 'incremental', 'rebuild')", name="ck_indicator_runs_kind"),
        sa.CheckConstraint("status IN ('running', 'completed', 'failed')", name="ck_indicator_runs_status"),
        sa.CheckConstraint("range_end IS NULL OR range_start IS NULL OR range_start <= range_end", name="ck_indicator_runs_range_order"),
        sa.CheckConstraint("input_count >= 0", name="ck_indicator_runs_input_count"),
        sa.CheckConstraint("result_count >= 0", name="ck_indicator_runs_result_count"),
        sa.CheckConstraint("excluded_count >= 0", name="ck_indicator_runs_excluded_count"),
        sa.CheckConstraint(
            "status <> 'completed' OR (input_hash IS NOT NULL AND result_hash IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_indicator_runs_completed_evidence",
        ),
    )
    op.create_index("ix_indicator_runs_generation_status", "indicator_calculation_runs", ["generation_id", "status"])
    op.create_index("ix_indicator_runs_series", "indicator_calculation_runs", ["series_id"])
    op.create_index(
        "uq_indicator_runs_one_running_per_series", "indicator_calculation_runs", ["series_id"], unique=True,
        postgresql_where=sa.text("status = 'running'"), sqlite_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "indicator_input_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("calculation_run_id", sa.Integer(), nullable=False),
        sa.Column("generation_id", sa.Integer(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("source_symbol_id", sa.Integer(), sa.ForeignKey("symbols.id"), nullable=True),
        sa.Column("price_observation_id", sa.Integer(), sa.ForeignKey("price_observations.id"), nullable=True),
        sa.Column("price_observation_identity_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("provider_symbol_mapping_id", sa.Integer(), sa.ForeignKey("provider_symbols.id"), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("provider_symbol", sa.String(length=50), nullable=False),
        sa.Column("adjustment_type", sa.String(length=100), nullable=True),
        sa.Column("parser_version", sa.String(length=100), nullable=True),
        sa.Column("close", sa.Numeric(), nullable=True),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
        sa.Column("mapping_status", sa.String(length=30), nullable=True),
        sa.Column("mapping_valid_from", sa.Date(), nullable=True),
        sa.Column("mapping_valid_to", sa.Date(), nullable=True),
        sa.Column("resolver_version", sa.String(length=100), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correction_ids", sa.JSON(), nullable=False),
        sa.Column("validation_evidence", sa.JSON(), nullable=False),
        sa.Column("input_status", sa.String(length=30), nullable=False),
        sa.Column("reason_code", sa.String(length=100), nullable=True),
        sa.Column("row_hash", sa.String(length=64), nullable=False),
        sa.Column("prefix_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("calculation_run_id", "generation_id", "trade_date", name="uq_indicator_input_snapshot_run_generation_date"),
        sa.ForeignKeyConstraint(
            ["calculation_run_id", "generation_id"],
            ["indicator_calculation_runs.id", "indicator_calculation_runs.generation_id"],
            name="fk_indicator_input_snapshot_run_generation",
        ),
        sa.ForeignKeyConstraint(
            ["price_observation_identity_snapshot_id", "price_observation_id"],
            [
                "price_observation_identity_snapshots.id",
                "price_observation_identity_snapshots.price_observation_id",
            ],
            name="fk_indicator_input_snapshot_identity_observation",
        ),
        sa.CheckConstraint(
            "input_status IN ('eligible', 'missing', 'invalid', 'review_required', 'confirmed_trading_halt')",
            name="ck_indicator_input_snapshots_status",
        ),
        sa.CheckConstraint(
            "reason_code IS NULL OR reason_code IN ('warming_up', 'missing_selected_source', 'identity_unavailable', 'ambiguous_identity_mapping', 'conflicting_observations', 'approved_exclusion', 'approved_validation_exclusion', 'open_validation_case', 'invalid_approved_correction', 'invalid_ohlcv', 'provider_or_adjustment_discontinuity', 'confirmed_trading_halt')",
            name="ck_indicator_input_snapshots_reason",
        ),
        sa.CheckConstraint(
            "price_observation_identity_snapshot_id IS NULL OR price_observation_id IS NOT NULL",
            name="ck_indicator_input_snapshots_identity_requires_observation",
        ),
        sa.CheckConstraint(
            "mapping_status IS NULL OR mapping_status IN ('matched', 'unmatched', 'ambiguous', 'invalid_legacy')",
            name="ck_indicator_input_snapshots_mapping_status",
        ),
        sa.CheckConstraint(
            "mapping_valid_to IS NULL OR mapping_valid_from IS NULL OR mapping_valid_from < mapping_valid_to",
            name="ck_indicator_input_snapshots_mapping_range",
        ),
    )
    op.create_index("ix_indicator_input_snapshots_run_date", "indicator_input_snapshots", ["calculation_run_id", "trade_date"])
    op.create_index("ix_indicator_input_snapshots_generation", "indicator_input_snapshots", ["generation_id"])
    op.create_index("ix_indicator_input_snapshots_instrument", "indicator_input_snapshots", ["instrument_id"])
    op.create_index("ix_indicator_input_snapshots_source_symbol", "indicator_input_snapshots", ["source_symbol_id"])
    op.create_index("ix_indicator_input_snapshots_observation", "indicator_input_snapshots", ["price_observation_id"])
    op.create_index("ix_indicator_input_snapshots_identity_snapshot", "indicator_input_snapshots", ["price_observation_identity_snapshot_id"])
    op.create_index("ix_indicator_input_snapshots_provider_mapping", "indicator_input_snapshots", ["provider_symbol_mapping_id"])

    op.create_table(
        "indicator_values",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("calculation_run_id", sa.Integer(), nullable=False),
        sa.Column("generation_id", sa.Integer(), nullable=False),
        sa.Column("period", sa.Integer(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("reason_code", sa.String(length=100), nullable=True),
        sa.Column("available_observations", sa.Integer(), nullable=False),
        sa.Column("input_prefix_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("calculation_run_id", "generation_id", "period", "trade_date", name="uq_indicator_value_run_generation_period_date"),
        sa.ForeignKeyConstraint(
            ["calculation_run_id", "generation_id"],
            ["indicator_calculation_runs.id", "indicator_calculation_runs.generation_id"],
            name="fk_indicator_value_run_generation",
        ),
        sa.CheckConstraint("period IN (5, 20, 50, 200)", name="ck_indicator_values_period"),
        sa.CheckConstraint("status IN ('warming_up', 'available', 'data_unavailable')", name="ck_indicator_values_status"),
        sa.CheckConstraint(
            "reason_code IS NULL OR reason_code IN ('warming_up', 'missing_selected_source', 'identity_unavailable', 'ambiguous_identity_mapping', 'conflicting_observations', 'approved_exclusion', 'approved_validation_exclusion', 'open_validation_case', 'invalid_approved_correction', 'invalid_ohlcv', 'provider_or_adjustment_discontinuity', 'confirmed_trading_halt')",
            name="ck_indicator_values_reason",
        ),
        sa.CheckConstraint(
            "(status = 'available' AND value IS NOT NULL AND reason_code IS NULL) "
            "OR (status = 'warming_up' AND value IS NOT NULL AND reason_code = 'warming_up') "
            "OR (status = 'data_unavailable' AND value IS NULL AND reason_code IS NOT NULL)",
            name="ck_indicator_values_status_shape",
        ),
        sa.CheckConstraint("available_observations >= 0", name="ck_indicator_values_available_observations"),
    )
    op.create_index("ix_indicator_values_run_period_date", "indicator_values", ["calculation_run_id", "period", "trade_date"])
    op.create_index("ix_indicator_values_generation", "indicator_values", ["generation_id"])

    if op.get_bind().dialect.name == "postgresql":
        _create_postgresql_immutability_triggers()


def _create_postgresql_immutability_triggers() -> None:
    op.execute("""
        CREATE FUNCTION indicator_prevent_identity_snapshot_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'price observation identity snapshots are immutable';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_price_observation_identity_snapshots_immutable
        BEFORE UPDATE OR DELETE ON price_observation_identity_snapshots
        FOR EACH ROW EXECUTE FUNCTION indicator_prevent_identity_snapshot_mutation()
    """)
    op.execute("""
        CREATE FUNCTION indicator_prevent_completed_run_mutation() RETURNS trigger AS $$
        BEGIN
            IF OLD.status = 'completed' THEN
                RAISE EXCEPTION 'completed indicator calculation runs are immutable';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_indicator_runs_completed_immutable
        BEFORE UPDATE OR DELETE ON indicator_calculation_runs
        FOR EACH ROW EXECUTE FUNCTION indicator_prevent_completed_run_mutation()
    """)
    op.execute("""
        CREATE FUNCTION indicator_prevent_completed_child_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'INSERT' AND EXISTS (
                SELECT 1 FROM indicator_calculation_runs
                WHERE id = NEW.calculation_run_id AND status = 'completed'
            ) THEN
                RAISE EXCEPTION 'completed indicator calculation run children are immutable';
            ELSIF TG_OP = 'DELETE' AND EXISTS (
                SELECT 1 FROM indicator_calculation_runs
                WHERE id = OLD.calculation_run_id AND status = 'completed'
            ) THEN
                RAISE EXCEPTION 'completed indicator calculation run children are immutable';
            ELSIF TG_OP = 'UPDATE' AND EXISTS (
                SELECT 1 FROM indicator_calculation_runs
                WHERE id IN (OLD.calculation_run_id, NEW.calculation_run_id)
                  AND status = 'completed'
            ) THEN
                RAISE EXCEPTION 'completed indicator calculation run children are immutable';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_indicator_input_snapshots_completed_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON indicator_input_snapshots
        FOR EACH ROW EXECUTE FUNCTION indicator_prevent_completed_child_mutation()
    """)
    op.execute("""
        CREATE TRIGGER trg_indicator_values_completed_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON indicator_values
        FOR EACH ROW EXECUTE FUNCTION indicator_prevent_completed_child_mutation()
    """)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_indicator_values_completed_immutable ON indicator_values")
        op.execute("DROP TRIGGER IF EXISTS trg_indicator_input_snapshots_completed_immutable ON indicator_input_snapshots")
        op.execute("DROP TRIGGER IF EXISTS trg_indicator_runs_completed_immutable ON indicator_calculation_runs")
        op.execute("DROP TRIGGER IF EXISTS trg_price_observation_identity_snapshots_immutable ON price_observation_identity_snapshots")
        op.execute("DROP FUNCTION IF EXISTS indicator_prevent_completed_child_mutation()")
        op.execute("DROP FUNCTION IF EXISTS indicator_prevent_completed_run_mutation()")
        op.execute("DROP FUNCTION IF EXISTS indicator_prevent_identity_snapshot_mutation()")
    op.drop_table("indicator_values")
    op.drop_table("indicator_input_snapshots")
    op.drop_table("indicator_calculation_runs")
    op.drop_table("indicator_generations")
    op.drop_table("indicator_series")
    op.drop_table("price_observation_identity_snapshots")
