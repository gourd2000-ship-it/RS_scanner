"""역사 OHLCV 데이터셋에 고정 identity와 품질 근거 추가.

Revision ID: p9c0d1e2f3a4
Revises: o8b9c0d1e2f3
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "o8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    membership_columns = {column["name"] for column in inspector.get_columns("backtest_dataset_memberships")}
    price_columns = {column["name"] for column in inspector.get_columns("backtest_dataset_prices")}
    for name, kind in (
        ("code", sa.String(20)),
        ("name", sa.String(255)),
        ("quality_status", sa.String(30)),
        ("quality_reason", sa.String(100)),
        ("quality_evidence", sa.JSON()),
    ):
        if name not in membership_columns:
            op.add_column("backtest_dataset_memberships", sa.Column(name, kind, nullable=True))
    if "correction_ids" not in price_columns:
        op.add_column("backtest_dataset_prices", sa.Column("correction_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    for name in ("quality_evidence", "quality_reason", "quality_status", "name", "code"):
        op.drop_column("backtest_dataset_memberships", name)
    op.drop_column("backtest_dataset_prices", "correction_ids")
