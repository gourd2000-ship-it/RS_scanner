"""Allow historical KRX code reuse without changing legacy price ownership.

Revision ID: h2b3c4d5e6f7
Revises: g3a4b5c6d7e8
Create Date: 2026-09-05 23:40:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "g3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop only the historical-identity blocker; leave ``symbols`` and prices intact."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("instruments"):
        return
    unique_names = {
        constraint.get("name")
        for constraint in inspector.get_unique_constraints("instruments")
    }
    if "uq_instruments_krx_short_code" in unique_names:
        op.drop_constraint("uq_instruments_krx_short_code", "instruments", type_="unique")
    indexes = {index.get("name") for index in inspector.get_indexes("instruments")}
    if "ix_instruments_krx_short_code" not in indexes:
        op.create_index("ix_instruments_krx_short_code", "instruments", ["krx_short_code"])


def downgrade() -> None:
    op.drop_index("ix_instruments_krx_short_code", table_name="instruments")
    op.create_unique_constraint("uq_instruments_krx_short_code", "instruments", ["krx_short_code"])
