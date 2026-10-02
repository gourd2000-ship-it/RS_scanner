"""Persist input-time candidate exclusions for reproducible execution.

Revision ID: t2d1e2f3a4b5
Revises: t2c1d2e3f4a5
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "t2d1e2f3a4b5"
down_revision: Union[str, Sequence[str], None] = "t2c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "backtest_runs",
        sa.Column("candidate_exclusions", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.alter_column("backtest_runs", "candidate_exclusions", server_default=None)


def downgrade() -> None:
    op.drop_column("backtest_runs", "candidate_exclusions")
