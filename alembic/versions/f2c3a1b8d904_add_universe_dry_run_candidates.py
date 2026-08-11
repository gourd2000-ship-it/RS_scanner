"""Store universe reconcile dry-run candidates.

Revision ID: f2c3a1b8d904
Revises: e48c1d7f0a32
Create Date: 2026-08-11 00:00:00
"""

from typing import Sequence, Union

from alembic import context
from alembic import op
import sqlalchemy as sa


revision: str = "f2c3a1b8d904"
down_revision: Union[str, Sequence[str], None] = "e48c1d7f0a32"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if context.is_offline_mode() or "deactivation_candidates" not in {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("symbol_universe_snapshots")
    }:
        op.add_column(
            "symbol_universe_snapshots",
            sa.Column("deactivation_candidates", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("symbol_universe_snapshots", "deactivation_candidates")
