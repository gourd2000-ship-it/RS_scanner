"""Allow partial batch completion status.

Revision ID: 9b7d5e2c1a04
Revises: 1f39d316eec9
Create Date: 2026-08-11 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9b7d5e2c1a04"
down_revision: Union[str, Sequence[str], None] = "615f876db25d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "crawl_jobs",
        "status",
        existing_type=sa.String(length=20),
        type_=sa.String(length=30),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "crawl_jobs",
        "status",
        existing_type=sa.String(length=30),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
