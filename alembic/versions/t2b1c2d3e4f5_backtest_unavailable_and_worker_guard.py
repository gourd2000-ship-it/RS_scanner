"""Record data-unavailable attempts and enforce one running backtest.

Revision ID: t2b1c2d3e4f5
Revises: t2a1b2c3d4e5
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "t2b1c2d3e4f5"
down_revision: Union[str, Sequence[str], None] = "t2a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("backtest_runs") as batch:
        batch.alter_column("backtest_dataset_id", nullable=True)
        batch.alter_column("backtest_dataset_rs_run_id", nullable=True)
        batch.alter_column("dataset_id", nullable=True)
        batch.alter_column("dataset_manifest_hash", nullable=True)
        batch.add_column(sa.Column("rs_formula_version", sa.String(100), nullable=True))
        batch.alter_column("rs_result_hash", nullable=True)
    op.create_index(
        "uq_backtest_runs_only_one_running", "backtest_runs", ["status"], unique=True,
        postgresql_where=sa.text("status = 'running'"), sqlite_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    op.drop_index("uq_backtest_runs_only_one_running", table_name="backtest_runs")
    with op.batch_alter_table("backtest_runs") as batch:
        batch.alter_column("rs_result_hash", nullable=False)
        batch.drop_column("rs_formula_version")
        batch.alter_column("dataset_manifest_hash", nullable=False)
        batch.alter_column("dataset_id", nullable=False)
        batch.alter_column("backtest_dataset_rs_run_id", nullable=False)
        batch.alter_column("backtest_dataset_id", nullable=False)
