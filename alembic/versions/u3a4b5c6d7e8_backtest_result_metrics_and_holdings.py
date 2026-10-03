"""Persist immutable backtest result metrics and daily holdings snapshots.

Revision ID: u3a4b5c6d7e8
Revises: t2d1e2f3a4b5
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "u3a4b5c6d7e8"
down_revision: Union[str, Sequence[str], None] = "t2d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("backtest_runs") as batch:
        batch.add_column(sa.Column("metrics", sa.JSON(), nullable=True))
    with op.batch_alter_table("backtest_daily_equity") as batch:
        batch.add_column(sa.Column("holdings", sa.JSON(), nullable=True))
    op.execute("UPDATE backtest_daily_equity SET holdings = '{}' WHERE holdings IS NULL")
    with op.batch_alter_table("backtest_daily_equity") as batch:
        batch.alter_column("holdings", nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("backtest_daily_equity") as batch:
        batch.drop_column("holdings")
    with op.batch_alter_table("backtest_runs") as batch:
        batch.drop_column("metrics")
