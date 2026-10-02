"""Include RS formula version in immutable backtest run inputs.

Revision ID: t2c1d2e3f4a5
Revises: t2b1c2d3e4f5
"""

from typing import Sequence, Union

from alembic import op


revision: str = "t2c1d2e3f4a5"
down_revision: Union[str, Sequence[str], None] = "t2b1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_transition_function(*, include_formula: bool) -> None:
    formula_guard = "OR NEW.rs_formula_version IS DISTINCT FROM OLD.rs_formula_version" if include_formula else ""
    op.execute(f"""
        CREATE FUNCTION backtest_enforce_run_transition() RETURNS trigger AS $$
        BEGIN
            IF NEW.backtest_strategy_version_id IS DISTINCT FROM OLD.backtest_strategy_version_id
               OR NEW.backtest_dataset_id IS DISTINCT FROM OLD.backtest_dataset_id
               OR NEW.backtest_dataset_rs_run_id IS DISTINCT FROM OLD.backtest_dataset_rs_run_id
               OR NEW.dataset_id IS DISTINCT FROM OLD.dataset_id
               OR NEW.dataset_manifest_hash IS DISTINCT FROM OLD.dataset_manifest_hash
               {formula_guard}
               OR NEW.rs_result_hash IS DISTINCT FROM OLD.rs_result_hash
               OR NEW.range_start IS DISTINCT FROM OLD.range_start
               OR NEW.range_end IS DISTINCT FROM OLD.range_end
               OR NEW.markets::text IS DISTINCT FROM OLD.markets::text THEN
                RAISE EXCEPTION 'backtest run inputs are immutable';
            END IF;
            IF OLD.status IN ('cancelled', 'failed', 'data_unavailable', 'completed') THEN
                RAISE EXCEPTION 'terminal backtest run is immutable';
            END IF;
            IF OLD.status <> NEW.status
               AND NOT ((OLD.status = 'queued' AND NEW.status IN ('running', 'cancelled', 'data_unavailable'))
                     OR (OLD.status = 'running' AND NEW.status IN ('completed', 'failed'))) THEN
                RAISE EXCEPTION 'invalid backtest status transition: % -> %', OLD.status, NEW.status;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS trg_backtest_runs_transition ON backtest_runs")
    op.execute("DROP FUNCTION IF EXISTS backtest_enforce_run_transition()")
    _create_transition_function(include_formula=True)
    op.execute("""
        CREATE TRIGGER trg_backtest_runs_transition
        BEFORE UPDATE ON backtest_runs
        FOR EACH ROW EXECUTE FUNCTION backtest_enforce_run_transition()
    """)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS trg_backtest_runs_transition ON backtest_runs")
    op.execute("DROP FUNCTION IF EXISTS backtest_enforce_run_transition()")
    _create_transition_function(include_formula=False)
    op.execute("""
        CREATE TRIGGER trg_backtest_runs_transition
        BEFORE UPDATE ON backtest_runs
        FOR EACH ROW EXECUTE FUNCTION backtest_enforce_run_transition()
    """)
