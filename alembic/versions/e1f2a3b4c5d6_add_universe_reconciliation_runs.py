"""Add persisted KRX/Naver reconciliation runs.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-08-20 05:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("universe_reconciliation_runs"):
        op.create_table(
            "universe_reconciliation_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("krx_snapshot_id", sa.Integer(), nullable=False),
            sa.Column("naver_snapshot_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="pending_review"),
            sa.Column("report", sa.JSON(), nullable=False),
            sa.Column("decision", sa.String(length=30), nullable=True),
            sa.Column("approved_by", sa.String(length=100), nullable=True),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["krx_snapshot_id"], ["krx_universe_snapshots.id"]),
            sa.ForeignKeyConstraint(["naver_snapshot_id"], ["symbol_universe_snapshots.id"]),
            sa.UniqueConstraint(
                "krx_snapshot_id", "naver_snapshot_id",
                name="uq_universe_reconciliation_snapshot_pair",
            ),
        )
        op.create_index(
            "ix_universe_reconciliation_runs_status_created",
            "universe_reconciliation_runs",
            ["status", "created_at"],
        )


def downgrade() -> None:
    op.drop_index(
        "ix_universe_reconciliation_runs_status_created",
        table_name="universe_reconciliation_runs",
    )
    op.drop_table("universe_reconciliation_runs")
