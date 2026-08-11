"""Allow error-bearing checkpoint completion statuses.

Revision ID: 7b5f3a1c9d22
Revises: 6a4e2f9c7b11
Create Date: 2026-08-11 10:35:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7b5f3a1c9d22"
down_revision: Union[str, Sequence[str], None] = "6a4e2f9c7b11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "batch_checkpoints",
        "status",
        existing_type=sa.String(length=20),
        type_=sa.String(length=30),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "batch_checkpoints",
        "status",
        existing_type=sa.String(length=30),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
