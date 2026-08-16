"""Store one-month returns with each RS score.

Revision ID: f6a7b8c9d0e1
Revises: e4f5a6b7c8d9
Create Date: 2026-08-16 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    column_names = {column["name"] for column in inspector.get_columns("rs_scores")}
    if "return_1m" not in column_names:
        op.add_column("rs_scores", sa.Column("return_1m", sa.Numeric(12, 6), nullable=True))

    # Existing RS records already have at least 253 price rows.  Backfill the
    # 21-trading-day return so the dashboard is useful immediately after deploy.
    op.execute(
        """
        WITH price_history AS (
            SELECT
                symbol_id,
                trade_date,
                close,
                LAG(close, 21) OVER (
                    PARTITION BY symbol_id
                    ORDER BY trade_date
                ) AS close_1m_ago
            FROM daily_prices
        )
        UPDATE rs_scores AS rs
        SET return_1m = (price_history.close / NULLIF(price_history.close_1m_ago, 0)) - 1
        FROM price_history
        WHERE rs.symbol_id = price_history.symbol_id
          AND rs.trade_date = price_history.trade_date
          AND price_history.close_1m_ago IS NOT NULL
        """
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    column_names = {column["name"] for column in inspector.get_columns("rs_scores")}
    if "return_1m" in column_names:
        op.drop_column("rs_scores", "return_1m")
