"""Preserve terminal backtest execution history.

Revision ID: s2c3d4e5f6a7
Revises: r1b2c3d4e5f6
"""

from typing import Sequence, Union

from alembic import op


revision: str = "s2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "r1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("""
        CREATE FUNCTION backtest_prevent_terminal_run_deletion() RETURNS trigger AS $$
        BEGIN
            IF OLD.status IN ('cancelled', 'failed', 'data_unavailable', 'completed') THEN
                RAISE EXCEPTION 'terminal backtest run history cannot be deleted';
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_backtest_runs_terminal_delete
        BEFORE DELETE ON backtest_runs
        FOR EACH ROW EXECUTE FUNCTION backtest_prevent_terminal_run_deletion()
    """)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS trg_backtest_runs_terminal_delete ON backtest_runs")
    op.execute("DROP FUNCTION IF EXISTS backtest_prevent_terminal_run_deletion()")
