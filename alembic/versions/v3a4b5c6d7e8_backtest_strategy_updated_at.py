"""Add strategy update timestamp for immutable version history.

Revision ID: v3a4b5c6d7e8
Revises: u3a4b5c6d7e8
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "v3a4b5c6d7e8"
down_revision: Union[str, Sequence[str], None] = "u3a4b5c6d7e8"
branch_labels = None
depends_on = None

def upgrade() -> None:
    with op.batch_alter_table("backtest_strategies") as batch:
        batch.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE backtest_strategies SET updated_at = created_at WHERE updated_at IS NULL")
    with op.batch_alter_table("backtest_strategies") as batch:
        batch.alter_column("updated_at", nullable=False)

def downgrade() -> None:
    with op.batch_alter_table("backtest_strategies") as batch:
        batch.drop_column("updated_at")
