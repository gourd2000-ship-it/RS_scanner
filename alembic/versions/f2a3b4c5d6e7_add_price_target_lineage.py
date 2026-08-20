"""Add immutable KRX target lineage to crawl results.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-08-20 05:40:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("crawl_target_results", sa.Column("krx_snapshot_id", sa.Integer(), nullable=True))
    op.add_column("crawl_target_results", sa.Column("instrument_id", sa.Integer(), nullable=True))
    op.add_column("crawl_target_results", sa.Column("price_eligibility", sa.String(length=30), nullable=True))
    op.add_column("crawl_target_results", sa.Column("eligibility_reason", sa.String(length=100), nullable=True))
    op.create_foreign_key(
        "fk_crawl_target_results_krx_snapshot_id", "crawl_target_results", "krx_universe_snapshots",
        ["krx_snapshot_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_crawl_target_results_instrument_id", "crawl_target_results", "instruments",
        ["instrument_id"], ["id"],
    )
    op.create_index("ix_crawl_target_results_krx_snapshot_id", "crawl_target_results", ["krx_snapshot_id"])
    op.create_index("ix_crawl_target_results_instrument_id", "crawl_target_results", ["instrument_id"])


def downgrade() -> None:
    op.drop_index("ix_crawl_target_results_instrument_id", table_name="crawl_target_results")
    op.drop_index("ix_crawl_target_results_krx_snapshot_id", table_name="crawl_target_results")
    op.drop_constraint("fk_crawl_target_results_instrument_id", "crawl_target_results", type_="foreignkey")
    op.drop_constraint("fk_crawl_target_results_krx_snapshot_id", "crawl_target_results", type_="foreignkey")
    op.drop_column("crawl_target_results", "eligibility_reason")
    op.drop_column("crawl_target_results", "price_eligibility")
    op.drop_column("crawl_target_results", "instrument_id")
    op.drop_column("crawl_target_results", "krx_snapshot_id")
