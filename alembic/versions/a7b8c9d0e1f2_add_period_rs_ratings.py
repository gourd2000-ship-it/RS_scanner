"""Add period RS ratings and cross-market ranks.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-16 14:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    column_names = {column["name"] for column in inspector.get_columns("rs_scores")}
    for name in ("rs_1m", "rs_3m", "rs_6m", "rs_12m", "rank_in_universe"):
        if name not in column_names:
            op.add_column(
                "rs_scores",
                sa.Column(name, sa.Integer(), nullable=False, server_default="0"),
            )

    op.create_index(
        "ix_rs_scores_trade_date_universe_rank",
        "rs_scores",
        ["trade_date", "rank_in_universe"],
        if_not_exists=True,
    )

    # 원시 종가 수익률을 전체(KOSPI+KOSDAQ) 유니버스 안에서 기간별 RS 1~99로
    # 변환한다. percent_rank는 동률 종목에 같은 점수를 부여한다.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                FLOOR(PERCENT_RANK() OVER (
                    PARTITION BY trade_date ORDER BY return_1m ASC NULLS FIRST
                ) * 98) + 1 AS rs_1m,
                FLOOR(PERCENT_RANK() OVER (
                    PARTITION BY trade_date ORDER BY return_3m ASC
                ) * 98) + 1 AS rs_3m,
                FLOOR(PERCENT_RANK() OVER (
                    PARTITION BY trade_date ORDER BY return_6m ASC
                ) * 98) + 1 AS rs_6m,
                FLOOR(PERCENT_RANK() OVER (
                    PARTITION BY trade_date ORDER BY return_12m ASC
                ) * 98) + 1 AS rs_12m,
                ROW_NUMBER() OVER (
                    PARTITION BY trade_date
                    ORDER BY
                        relative_return_score DESC,
                        return_12m DESC,
                        return_6m DESC,
                        return_3m DESC,
                        return_1m DESC NULLS LAST,
                        symbol_id ASC
                ) AS rank_in_universe
            FROM rs_scores
        )
        UPDATE rs_scores AS rs
        SET
            rs_1m = ranked.rs_1m,
            rs_3m = ranked.rs_3m,
            rs_6m = ranked.rs_6m,
            rs_12m = ranked.rs_12m,
            rank_in_universe = ranked.rank_in_universe
        FROM ranked
        WHERE rs.id = ranked.id
        """
    )


def downgrade() -> None:
    op.drop_index("ix_rs_scores_trade_date_universe_rank", table_name="rs_scores", if_exists=True)
    inspector = sa.inspect(op.get_bind())
    column_names = {column["name"] for column in inspector.get_columns("rs_scores")}
    for name in ("rank_in_universe", "rs_12m", "rs_6m", "rs_3m", "rs_1m"):
        if name in column_names:
            op.drop_column("rs_scores", name)
