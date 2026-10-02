"""Add composite indexes for bounded materialized-backtest API replay.

Revision ID: o8b9c0d1e2f3
Revises: n7a8b9c0d1e2
Create Date: 2026-09-06 23:48:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "o8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "n7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = op.get_bind().dialect
    if inspector.name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_backtest_dataset_prices_dataset_instrument_date "
            "ON backtest_dataset_prices (backtest_dataset_id, instrument_id, trade_date)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_backtest_dataset_memberships_dataset_date_instrument "
            "ON backtest_dataset_memberships (backtest_dataset_id, trade_date, instrument_id)"
        )
    else:
        op.create_index(
            "ix_backtest_dataset_prices_dataset_instrument_date",
            "backtest_dataset_prices",
            ["backtest_dataset_id", "instrument_id", "trade_date"],
        )
        op.create_index(
            "ix_backtest_dataset_memberships_dataset_date_instrument",
            "backtest_dataset_memberships",
            ["backtest_dataset_id", "trade_date", "instrument_id"],
        )


def downgrade() -> None:
    op.drop_index("ix_backtest_dataset_memberships_dataset_date_instrument", table_name="backtest_dataset_memberships")
    op.drop_index("ix_backtest_dataset_prices_dataset_instrument_date", table_name="backtest_dataset_prices")
