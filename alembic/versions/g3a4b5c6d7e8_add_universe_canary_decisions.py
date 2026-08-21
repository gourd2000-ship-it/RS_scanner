"""Add immutable KRX canary operator decisions.

Revision ID: g3a4b5c6d7e8
Revises: f2a3b4c5d6e7
Create Date: 2026-08-21 08:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g3a4b5c6d7e8"
down_revision: Union[str, Sequence[str], None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # In local development, application startup can call ``create_all`` before
    # Alembic runs. The model schema is equivalent, so preserve that table and
    # advance the revision rather than failing on DuplicateTable.
    if sa.inspect(op.get_bind()).has_table("universe_canary_decisions"):
        return
    op.create_table(
        "universe_canary_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("crawl_job_id", sa.Integer(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("market", sa.String(length=20), nullable=False),
        sa.Column("krx_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("reconciliation_run_id", sa.Integer(), nullable=True),
        sa.Column("selected_reconciliation_run_id", sa.Integer(), nullable=True),
        sa.Column("authority", sa.String(length=40), nullable=False),
        sa.Column("fallback_reason", sa.String(length=100), nullable=True),
        sa.Column("mapping_rate", sa.Float(), nullable=True),
        sa.Column("target_count", sa.Integer(), nullable=False),
        sa.Column("operator_decision", sa.String(length=20), nullable=False),
        sa.Column("approved_by", sa.String(length=100), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["crawl_job_id"], ["crawl_jobs.id"]),
        sa.ForeignKeyConstraint(["krx_snapshot_id"], ["krx_universe_snapshots.id"]),
        sa.ForeignKeyConstraint(["reconciliation_run_id"], ["universe_reconciliation_runs.id"]),
        sa.ForeignKeyConstraint(["selected_reconciliation_run_id"], ["universe_reconciliation_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_date", "market", name="uq_universe_canary_decision_date_market"),
    )
    op.create_index("ix_universe_canary_decisions_job", "universe_canary_decisions", ["crawl_job_id"])


def downgrade() -> None:
    op.drop_index("ix_universe_canary_decisions_job", table_name="universe_canary_decisions")
    op.drop_table("universe_canary_decisions")
