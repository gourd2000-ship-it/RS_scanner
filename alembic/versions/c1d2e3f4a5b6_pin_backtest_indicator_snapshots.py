"""Pin immutable MA50 and ATR14 snapshots to queued backtest runs.

Revision ID: c1d2e3f4a5b6
Revises: b9c0d1e2f3a4
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_run_transition_function() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_backtest_runs_transition ON backtest_runs")
    op.execute("DROP FUNCTION IF EXISTS backtest_enforce_run_transition()")
    op.execute("""
        CREATE FUNCTION backtest_enforce_run_transition() RETURNS trigger AS $$
        BEGIN
            IF NEW.backtest_strategy_version_id IS DISTINCT FROM OLD.backtest_strategy_version_id
               OR NEW.backtest_dataset_id IS DISTINCT FROM OLD.backtest_dataset_id
               OR NEW.backtest_dataset_rs_run_id IS DISTINCT FROM OLD.backtest_dataset_rs_run_id
               OR NEW.dataset_id IS DISTINCT FROM OLD.dataset_id
               OR NEW.dataset_manifest_hash IS DISTINCT FROM OLD.dataset_manifest_hash
               OR NEW.rs_formula_version IS DISTINCT FROM OLD.rs_formula_version
               OR NEW.rs_result_hash IS DISTINCT FROM OLD.rs_result_hash
               OR NEW.volume_sma50_snapshot_id IS DISTINCT FROM OLD.volume_sma50_snapshot_id
               OR NEW.volume_sma50_snapshot_hash IS DISTINCT FROM OLD.volume_sma50_snapshot_hash
               OR NEW.atr14_snapshot_id IS DISTINCT FROM OLD.atr14_snapshot_id
               OR NEW.atr14_snapshot_hash IS DISTINCT FROM OLD.atr14_snapshot_hash
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
    op.execute("""
        CREATE TRIGGER trg_backtest_runs_transition
        BEFORE UPDATE ON backtest_runs
        FOR EACH ROW EXECUTE FUNCTION backtest_enforce_run_transition()
    """)


def upgrade() -> None:
    with op.batch_alter_table("backtest_runs") as batch:
        batch.add_column(sa.Column("volume_sma50_snapshot_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("volume_sma50_snapshot_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("atr14_snapshot_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("atr14_snapshot_hash", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_backtest_runs_volume_sma50_indicator_snapshot",
            "backtest_dataset_indicator_snapshots", ["volume_sma50_snapshot_id"], ["id"],
        )
        batch.create_foreign_key(
            "fk_backtest_runs_atr14_indicator_snapshot",
            "backtest_dataset_indicator_snapshots", ["atr14_snapshot_id"], ["id"],
        )
        batch.create_check_constraint(
            "ck_backtest_runs_volume_sma50_snapshot_pin",
            "(volume_sma50_snapshot_id IS NULL AND volume_sma50_snapshot_hash IS NULL) OR "
            "(volume_sma50_snapshot_id IS NOT NULL AND volume_sma50_snapshot_hash IS NOT NULL "
            "AND length(volume_sma50_snapshot_hash) = 64)",
        )
        batch.create_check_constraint(
            "ck_backtest_runs_atr14_snapshot_pin",
            "(atr14_snapshot_id IS NULL AND atr14_snapshot_hash IS NULL) OR "
            "(atr14_snapshot_id IS NOT NULL AND atr14_snapshot_hash IS NOT NULL "
            "AND length(atr14_snapshot_hash) = 64)",
        )
    op.create_index(
        "ix_backtest_runs_volume_sma50_snapshot_id", "backtest_runs", ["volume_sma50_snapshot_id"]
    )
    op.create_index("ix_backtest_runs_atr14_snapshot_id", "backtest_runs", ["atr14_snapshot_id"])

    if op.get_bind().dialect.name == "postgresql":
        _create_run_transition_function()
        op.execute("""
            CREATE FUNCTION backtest_validate_run_indicator_snapshot_pins() RETURNS trigger AS $$
            BEGIN
                IF NEW.volume_sma50_snapshot_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM backtest_dataset_indicator_snapshots snapshot
                    WHERE snapshot.id = NEW.volume_sma50_snapshot_id
                      AND snapshot.backtest_dataset_id = NEW.backtest_dataset_id
                      AND snapshot.dataset_manifest_hash = NEW.dataset_manifest_hash
                      AND snapshot.indicator_kind = 'volume_sma'
                      AND snapshot.period = 50
                      AND snapshot.formula_version = 'volume-sma-v1'
                      AND snapshot.status = 'complete'
                      AND snapshot.content_hash = NEW.volume_sma50_snapshot_hash
                ) THEN
                    RAISE EXCEPTION 'volume_sma50 snapshot does not match the backtest dataset and hash';
                END IF;
                IF NEW.atr14_snapshot_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM backtest_dataset_indicator_snapshots snapshot
                    WHERE snapshot.id = NEW.atr14_snapshot_id
                      AND snapshot.backtest_dataset_id = NEW.backtest_dataset_id
                      AND snapshot.dataset_manifest_hash = NEW.dataset_manifest_hash
                      AND snapshot.indicator_kind = 'atr'
                      AND snapshot.period = 14
                      AND snapshot.formula_version = 'wilder-atr-14-v1'
                      AND snapshot.status = 'complete'
                      AND snapshot.content_hash = NEW.atr14_snapshot_hash
                ) THEN
                    RAISE EXCEPTION 'atr14 snapshot does not match the backtest dataset and hash';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER trg_backtest_runs_indicator_snapshot_pins
            BEFORE INSERT ON backtest_runs
            FOR EACH ROW EXECUTE FUNCTION backtest_validate_run_indicator_snapshot_pins()
        """)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_backtest_runs_indicator_snapshot_pins ON backtest_runs")
        op.execute("DROP FUNCTION IF EXISTS backtest_validate_run_indicator_snapshot_pins()")
    op.drop_index("ix_backtest_runs_atr14_snapshot_id", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_volume_sma50_snapshot_id", table_name="backtest_runs")
    with op.batch_alter_table("backtest_runs") as batch:
        batch.drop_constraint("ck_backtest_runs_atr14_snapshot_pin", type_="check")
        batch.drop_constraint("ck_backtest_runs_volume_sma50_snapshot_pin", type_="check")
        batch.drop_constraint("fk_backtest_runs_atr14_indicator_snapshot", type_="foreignkey")
        batch.drop_constraint("fk_backtest_runs_volume_sma50_indicator_snapshot", type_="foreignkey")
        batch.drop_column("atr14_snapshot_hash")
        batch.drop_column("atr14_snapshot_id")
        batch.drop_column("volume_sma50_snapshot_hash")
        batch.drop_column("volume_sma50_snapshot_id")
    if op.get_bind().dialect.name == "postgresql":
        # Restore the transition function installed by t2c1d2e3f4a5.
        op.execute("DROP TRIGGER IF EXISTS trg_backtest_runs_transition ON backtest_runs")
        op.execute("DROP FUNCTION IF EXISTS backtest_enforce_run_transition()")
        op.execute("""
            CREATE FUNCTION backtest_enforce_run_transition() RETURNS trigger AS $$
            BEGIN
                IF NEW.backtest_strategy_version_id IS DISTINCT FROM OLD.backtest_strategy_version_id
                   OR NEW.backtest_dataset_id IS DISTINCT FROM OLD.backtest_dataset_id
                   OR NEW.backtest_dataset_rs_run_id IS DISTINCT FROM OLD.backtest_dataset_rs_run_id
                   OR NEW.dataset_id IS DISTINCT FROM OLD.dataset_id
                   OR NEW.dataset_manifest_hash IS DISTINCT FROM OLD.dataset_manifest_hash
                   OR NEW.rs_formula_version IS DISTINCT FROM OLD.rs_formula_version
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
        op.execute("""
            CREATE TRIGGER trg_backtest_runs_transition
            BEFORE UPDATE ON backtest_runs
            FOR EACH ROW EXECUTE FUNCTION backtest_enforce_run_transition()
        """)
