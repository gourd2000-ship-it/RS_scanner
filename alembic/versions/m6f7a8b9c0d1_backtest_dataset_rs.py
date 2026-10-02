"""Add immutable historical RS runs and rows for a backtest dataset.

Revision ID: m6f7a8b9c0d1
Revises: l5e6f7a8b9c0
Create Date: 2026-09-06 06:35:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "m6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "l5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    dataset_columns = {column["name"] for column in inspector.get_columns("backtest_datasets")}
    if "final_manifest_hash" not in dataset_columns:
        op.add_column("backtest_datasets", sa.Column("final_manifest_hash", sa.String(64), nullable=True))
    dataset_indexes = {index["name"] for index in inspector.get_indexes("backtest_datasets")}
    if "ix_backtest_datasets_final_manifest_hash" not in dataset_indexes:
        op.create_index("ix_backtest_datasets_final_manifest_hash", "backtest_datasets", ["final_manifest_hash"], unique=True)
    if not inspector.has_table("backtest_dataset_rs_runs"):
        op.create_table("backtest_dataset_rs_runs",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("backtest_dataset_id", sa.Integer(), nullable=False),
        sa.Column("formula_version", sa.String(100), nullable=False), sa.Column("policy_version", sa.String(100), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False), sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="completed"), sa.Column("manifest", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["backtest_dataset_id"], ["backtest_datasets.id"]), sa.UniqueConstraint("backtest_dataset_id", "formula_version", name="uq_backtest_dataset_rs_run"),
        )
        op.create_index("ix_backtest_dataset_rs_runs_backtest_dataset_id", "backtest_dataset_rs_runs", ["backtest_dataset_id"])
    if not inspector.has_table("backtest_dataset_rs"):
        op.create_table("backtest_dataset_rs",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("backtest_dataset_rs_run_id", sa.Integer(), nullable=False), sa.Column("backtest_dataset_id", sa.Integer(), nullable=False), sa.Column("instrument_id", sa.Integer(), nullable=False), sa.Column("code", sa.String(20), nullable=False), sa.Column("market", sa.String(20), nullable=False), sa.Column("trade_date", sa.Date(), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("reason_code", sa.String(80), nullable=True), sa.Column("required_observations", sa.Integer(), nullable=False), sa.Column("available_observations", sa.Integer(), nullable=False), sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("return_1m", sa.Numeric(18,8), nullable=True), sa.Column("return_3m", sa.Numeric(18,8), nullable=True), sa.Column("return_6m", sa.Numeric(18,8), nullable=True), sa.Column("return_9m", sa.Numeric(18,8), nullable=True), sa.Column("return_12m", sa.Numeric(18,8), nullable=True), sa.Column("relative_return_score", sa.Numeric(18,8), nullable=True), sa.Column("rs_percentile", sa.Numeric(18,8), nullable=True), sa.Column("rs_1m", sa.Integer(), nullable=False, server_default="0"), sa.Column("rs_3m", sa.Integer(), nullable=False, server_default="0"), sa.Column("rs_6m", sa.Integer(), nullable=False, server_default="0"), sa.Column("rs_12m", sa.Integer(), nullable=False, server_default="0"), sa.Column("rs_rating", sa.Integer(), nullable=True), sa.Column("rank_in_market", sa.Integer(), nullable=True), sa.Column("rank_in_universe", sa.Integer(), nullable=True), sa.Column("input_hash", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["backtest_dataset_rs_run_id"], ["backtest_dataset_rs_runs.id"]), sa.ForeignKeyConstraint(["backtest_dataset_id"], ["backtest_datasets.id"]), sa.UniqueConstraint("backtest_dataset_rs_run_id", "instrument_id", "trade_date", name="uq_backtest_dataset_rs_target"),
        )
        op.create_index("ix_backtest_dataset_rs_backtest_dataset_rs_run_id", "backtest_dataset_rs", ["backtest_dataset_rs_run_id"])
        op.create_index("ix_backtest_dataset_rs_backtest_dataset_id", "backtest_dataset_rs", ["backtest_dataset_id"])
        op.create_index("ix_backtest_dataset_rs_instrument_id", "backtest_dataset_rs", ["instrument_id"])
        op.create_index("ix_backtest_dataset_rs_dataset_date", "backtest_dataset_rs", ["backtest_dataset_id", "trade_date"])

def downgrade() -> None:
    op.drop_table("backtest_dataset_rs")
    op.drop_table("backtest_dataset_rs_runs")
    if op.get_bind().dialect.name == "postgresql":
        # A development database may have applied this revision before its
        # final-manifest column was added; make that transition reversible.
        op.execute("DROP INDEX IF EXISTS ix_backtest_datasets_final_manifest_hash")
        op.execute("ALTER TABLE backtest_datasets DROP COLUMN IF EXISTS final_manifest_hash")
    else:
        op.drop_index("ix_backtest_datasets_final_manifest_hash", table_name="backtest_datasets")
        op.drop_column("backtest_datasets", "final_manifest_hash")
