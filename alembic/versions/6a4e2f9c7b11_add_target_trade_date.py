"""Store the provider trade date on per-target crawl results.

Revision ID: 6a4e2f9c7b11
Revises: f2c3a1b8d904
Create Date: 2026-08-11 00:00:00
"""

from typing import Sequence, Union

from alembic import context
from alembic import op
import sqlalchemy as sa


revision: str = "6a4e2f9c7b11"
down_revision: Union[str, Sequence[str], None] = "f2c3a1b8d904"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if context.is_offline_mode() or "trade_date" not in {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("crawl_target_results")
    }:
        op.add_column(
            "crawl_target_results",
            sa.Column("trade_date", sa.Date(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("crawl_target_results", "trade_date")
