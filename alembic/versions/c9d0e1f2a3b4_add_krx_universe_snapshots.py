"""Add KRX universe snapshots and memberships.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-08-20 03:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "krx_universe_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("crawl_job_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("scope", sa.String(length=50), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("members_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("members_valid", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=True),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["crawl_job_id"], ["crawl_jobs.id"]),
    )
    op.create_index(
        "ix_krx_universe_snapshots_scope_status_as_of",
        "krx_universe_snapshots",
        ["scope", "status", "as_of_date"],
    )
    op.create_index(
        "ix_krx_universe_snapshots_job_id",
        "krx_universe_snapshots",
        ["crawl_job_id"],
    )

    op.create_table(
        "krx_universe_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("isin", sa.String(length=20), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("market", sa.String(length=20), nullable=False),
        sa.Column("security_type", sa.String(length=20), nullable=False),
        sa.Column("listing_status", sa.String(length=30), nullable=False, server_default="listed_observed"),
        sa.Column("trading_status", sa.String(length=30), nullable=False, server_default="unknown"),
        sa.Column("listed_at", sa.Date(), nullable=True),
        sa.Column("raw_fields", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["krx_universe_snapshots.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("snapshot_id", "code", name="uq_krx_universe_membership_snapshot_code"),
    )
    op.create_index(
        "ix_krx_universe_memberships_snapshot_market",
        "krx_universe_memberships",
        ["snapshot_id", "market"],
    )
    op.create_index("ix_krx_universe_memberships_code", "krx_universe_memberships", ["code"])


def downgrade() -> None:
    op.drop_index("ix_krx_universe_memberships_code", table_name="krx_universe_memberships")
    op.drop_index("ix_krx_universe_memberships_snapshot_market", table_name="krx_universe_memberships")
    op.drop_table("krx_universe_memberships")
    op.drop_index("ix_krx_universe_snapshots_job_id", table_name="krx_universe_snapshots")
    op.drop_index("ix_krx_universe_snapshots_scope_status_as_of", table_name="krx_universe_snapshots")
    op.drop_table("krx_universe_snapshots")
