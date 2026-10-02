"""Require every persisted backtest run to enter through the queue.

Revision ID: r1b2c3d4e5f6
Revises: q0a1b2c3d4e5
"""

from typing import Sequence, Union

from alembic import op


revision: str = "r1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "q0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("""
        CREATE FUNCTION backtest_enforce_initial_run_status() RETURNS trigger AS $$
        BEGIN
            IF NEW.status <> 'queued' THEN
                RAISE EXCEPTION 'backtest runs must be inserted with queued status';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_backtest_runs_initial_status
        BEFORE INSERT ON backtest_runs
        FOR EACH ROW EXECUTE FUNCTION backtest_enforce_initial_run_status()
    """)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS trg_backtest_runs_initial_status ON backtest_runs")
    op.execute("DROP FUNCTION IF EXISTS backtest_enforce_initial_run_status()")
