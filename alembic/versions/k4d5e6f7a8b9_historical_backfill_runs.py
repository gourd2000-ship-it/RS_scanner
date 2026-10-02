"""Add resumable historical price backfill state and observation lineage.

Revision ID: k4d5e6f7a8b9
Revises: j3c4d5e6f7a8
Create Date: 2026-09-06 05:35:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "k4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "j3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("historical_backfill_runs"):
        op.create_table(
            "historical_backfill_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("run_id", sa.String(length=80), nullable=False),
            sa.Column("manifest_hash", sa.String(length=64), nullable=False),
            sa.Column("manifest", sa.JSON(), nullable=False),
            sa.Column("range_start", sa.Date(), nullable=False),
            sa.Column("range_end", sa.Date(), nullable=False),
            sa.Column("provider", sa.String(length=100), nullable=False),
            sa.Column("adjustment_type", sa.String(length=50), nullable=False),
            sa.Column("base_date", sa.String(length=8), nullable=False),
            sa.Column("request_budget", sa.Integer(), nullable=False),
            sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="running"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("run_id", name="uq_historical_backfill_runs_run_id"),
        )
        op.create_index("ix_historical_backfill_runs_run_id", "historical_backfill_runs", ["run_id"])
        op.create_index("ix_historical_backfill_runs_manifest_hash", "historical_backfill_runs", ["manifest_hash"])
        op.create_index("ix_historical_backfill_runs_status", "historical_backfill_runs", ["status"])
    if not inspector.has_table("historical_backfill_target_states"):
        op.create_table(
            "historical_backfill_target_states",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("historical_backfill_run_id", sa.Integer(), nullable=False),
            sa.Column("instrument_id", sa.Integer(), nullable=False),
            sa.Column("symbol_id", sa.Integer(), nullable=True),
            sa.Column("provider_code", sa.String(length=50), nullable=False),
            sa.Column("market", sa.String(length=20), nullable=False),
            sa.Column("expected_dates", sa.JSON(), nullable=False),
            sa.Column("confirmed_dates", sa.JSON(), nullable=False),
            sa.Column("remaining_dates", sa.JSON(), nullable=False),
            sa.Column("confirmed_from", sa.Date(), nullable=True),
            sa.Column("confirmed_through", sa.Date(), nullable=True),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
            sa.Column("failure_reason", sa.String(length=100), nullable=True),
            sa.Column("failure_evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["historical_backfill_run_id"], ["historical_backfill_runs.id"]),
            sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
            sa.ForeignKeyConstraint(["symbol_id"], ["symbols.id"]),
            sa.UniqueConstraint("historical_backfill_run_id", "instrument_id", "market", name="uq_backfill_target_run_instrument_market"),
        )
        op.create_index("ix_historical_backfill_target_states_historical_backfill_run_id", "historical_backfill_target_states", ["historical_backfill_run_id"])
        op.create_index("ix_historical_backfill_target_states_instrument_id", "historical_backfill_target_states", ["instrument_id"])
        op.create_index("ix_historical_backfill_target_states_symbol_id", "historical_backfill_target_states", ["symbol_id"])
        op.create_index("ix_backfill_target_run_status", "historical_backfill_target_states", ["historical_backfill_run_id", "status"])
    if inspector.has_table("price_observations"):
        columns = {column["name"] for column in inspector.get_columns("price_observations")}
        if "historical_backfill_run_id" not in columns:
            op.add_column("price_observations", sa.Column("historical_backfill_run_id", sa.Integer(), nullable=True))
            op.create_foreign_key("fk_price_observations_backfill_run", "price_observations", "historical_backfill_runs", ["historical_backfill_run_id"], ["id"])
            op.create_index("ix_price_observations_backfill_run", "price_observations", ["historical_backfill_run_id"])
        if "adjustment_type" not in columns:
            op.add_column("price_observations", sa.Column("adjustment_type", sa.String(length=50), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("price_observations"):
        columns = {column["name"] for column in inspector.get_columns("price_observations")}
        if "adjustment_type" in columns:
            op.drop_column("price_observations", "adjustment_type")
        if "historical_backfill_run_id" in columns:
            op.drop_index("ix_price_observations_backfill_run", table_name="price_observations")
            op.drop_constraint("fk_price_observations_backfill_run", "price_observations", type_="foreignkey")
            op.drop_column("price_observations", "historical_backfill_run_id")
    if inspector.has_table("historical_backfill_target_states"):
        op.drop_index("ix_backfill_target_run_status", table_name="historical_backfill_target_states")
        op.drop_table("historical_backfill_target_states")
    if inspector.has_table("historical_backfill_runs"):
        op.drop_index("ix_historical_backfill_runs_status", table_name="historical_backfill_runs")
        op.drop_index("ix_historical_backfill_runs_manifest_hash", table_name="historical_backfill_runs")
        op.drop_index("ix_historical_backfill_runs_run_id", table_name="historical_backfill_runs")
        op.drop_table("historical_backfill_runs")
