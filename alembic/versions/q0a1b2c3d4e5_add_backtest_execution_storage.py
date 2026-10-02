"""Add immutable strategy, execution, result and operator-session storage.

Revision ID: q0a1b2c3d4e5
Revises: p9c0d1e2f3a4
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "q0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "backtest_strategies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("strategy_id", sa.String(80), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("strategy_id", name="uq_backtest_strategies_strategy_id"),
    )
    op.create_index("ix_backtest_strategies_strategy_id", "backtest_strategies", ["strategy_id"])
    op.create_table(
        "backtest_strategy_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("backtest_strategy_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["backtest_strategy_id"], ["backtest_strategies.id"]),
        sa.UniqueConstraint("backtest_strategy_id", "version", name="uq_backtest_strategy_version"),
    )
    op.create_index("ix_backtest_strategy_versions_backtest_strategy_id", "backtest_strategy_versions", ["backtest_strategy_id"])
    op.create_index("ix_backtest_strategy_versions_config_hash", "backtest_strategy_versions", ["config_hash"])
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(80), nullable=False),
        sa.Column("backtest_strategy_version_id", sa.Integer(), nullable=False),
        sa.Column("backtest_dataset_id", sa.Integer(), nullable=False),
        sa.Column("backtest_dataset_rs_run_id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.String(80), nullable=False),
        sa.Column("dataset_manifest_hash", sa.String(64), nullable=False),
        sa.Column("rs_result_hash", sa.String(64), nullable=False),
        sa.Column("range_start", sa.Date(), nullable=False),
        sa.Column("range_end", sa.Date(), nullable=False),
        sa.Column("markets", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("status IN ('queued', 'running', 'cancelled', 'failed', 'data_unavailable', 'completed')", name="ck_backtest_runs_status"),
        sa.ForeignKeyConstraint(["backtest_strategy_version_id"], ["backtest_strategy_versions.id"]),
        sa.ForeignKeyConstraint(["backtest_dataset_id"], ["backtest_datasets.id"]),
        sa.ForeignKeyConstraint(["backtest_dataset_rs_run_id"], ["backtest_dataset_rs_runs.id"]),
        sa.UniqueConstraint("run_id", name="uq_backtest_runs_run_id"),
    )
    op.create_index("ix_backtest_runs_run_id", "backtest_runs", ["run_id"])
    op.create_index("ix_backtest_runs_queue", "backtest_runs", ["status", "queued_at", "id"])
    op.create_index("ix_backtest_runs_strategy_version", "backtest_runs", ["backtest_strategy_version_id"])
    op.create_index("ix_backtest_runs_dataset", "backtest_runs", ["backtest_dataset_id"])
    op.create_index("ix_backtest_runs_dataset_id", "backtest_runs", ["dataset_id"])
    op.create_index("ix_backtest_runs_dataset_manifest_hash", "backtest_runs", ["dataset_manifest_hash"])
    op.create_index("ix_backtest_runs_rs_result_hash", "backtest_runs", ["rs_result_hash"])
    op.create_table(
        "backtest_benchmark_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("backtest_run_id", sa.Integer(), nullable=False),
        sa.Column("market", sa.String(20), nullable=False),
        sa.Column("benchmark_code", sa.String(50), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["backtest_run_id"], ["backtest_runs.id"]),
        sa.UniqueConstraint("backtest_run_id", "market", name="uq_backtest_benchmark_snapshot_run_market"),
    )
    op.create_index("ix_backtest_benchmark_snapshots_backtest_run_id", "backtest_benchmark_snapshots", ["backtest_run_id"])
    op.create_index("ix_backtest_benchmark_snapshots_snapshot_hash", "backtest_benchmark_snapshots", ["snapshot_hash"])
    op.create_table(
        "backtest_benchmark_snapshot_prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("backtest_benchmark_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("close", sa.Numeric(18, 4), nullable=False),
        sa.ForeignKeyConstraint(["backtest_benchmark_snapshot_id"], ["backtest_benchmark_snapshots.id"]),
        sa.UniqueConstraint("backtest_benchmark_snapshot_id", "trade_date", name="uq_backtest_benchmark_snapshot_price"),
    )
    op.create_index("ix_backtest_benchmark_snapshot_prices_date", "backtest_benchmark_snapshot_prices", ["backtest_benchmark_snapshot_id", "trade_date"])
    op.create_table(
        "backtest_daily_equity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("backtest_run_id", sa.Integer(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("cash", sa.Numeric(18, 2), nullable=False),
        sa.Column("holdings_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("net_asset_value", sa.Numeric(18, 2), nullable=False),
        sa.ForeignKeyConstraint(["backtest_run_id"], ["backtest_runs.id"]),
        sa.UniqueConstraint("backtest_run_id", "trade_date", name="uq_backtest_daily_equity_run_date"),
    )
    op.create_index("ix_backtest_daily_equity_run_date", "backtest_daily_equity", ["backtest_run_id", "trade_date"])
    op.create_table(
        "backtest_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("backtest_run_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("execution_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("execution_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("fee", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("slippage", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="filled"),
        sa.ForeignKeyConstraint(["backtest_run_id"], ["backtest_runs.id"]),
        sa.UniqueConstraint("backtest_run_id", "sequence", name="uq_backtest_order_run_sequence"),
    )
    op.create_index("ix_backtest_orders_run_execution", "backtest_orders", ["backtest_run_id", "execution_date"])
    op.create_table(
        "backtest_trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("backtest_run_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("exit_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("entry_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("exit_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("profit_loss", sa.Numeric(18, 2), nullable=False),
        sa.Column("return_rate", sa.Numeric(18, 8), nullable=False),
        sa.Column("exit_reason_codes", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["backtest_run_id"], ["backtest_runs.id"]),
    )
    op.create_index("ix_backtest_trades_run_exit", "backtest_trades", ["backtest_run_id", "exit_date"])
    op.create_table(
        "backtest_operator_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_token_hash", sa.String(64), nullable=False),
        sa.Column("operator_subject_hash", sa.String(64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("session_token_hash", name="uq_backtest_operator_sessions_token_hash"),
    )
    op.create_index("ix_backtest_operator_sessions_token_hash", "backtest_operator_sessions", ["session_token_hash"])
    op.create_index("ix_backtest_operator_sessions_expiry", "backtest_operator_sessions", ["expires_at", "revoked_at"])
    op.create_table(
        "backtest_operator_login_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject_hash", sa.String(64), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_backtest_operator_login_attempts_subject_time", "backtest_operator_login_attempts", ["subject_hash", "attempted_at"])
    op.create_table(
        "backtest_operator_lockouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject_hash", sa.String(64), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("subject_hash", name="uq_backtest_operator_lockouts_subject_hash"),
    )
    op.create_index("ix_backtest_operator_lockouts_subject_hash", "backtest_operator_lockouts", ["subject_hash"])
    op.create_index("ix_backtest_operator_lockouts_locked_until", "backtest_operator_lockouts", ["locked_until"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION backtest_prevent_strategy_version_change() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION 'backtest strategy versions are immutable'; END;
            $$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER trg_backtest_strategy_versions_immutable
            BEFORE UPDATE OR DELETE ON backtest_strategy_versions
            FOR EACH ROW EXECUTE FUNCTION backtest_prevent_strategy_version_change()
        """)
        op.execute("""
            CREATE FUNCTION backtest_enforce_run_transition() RETURNS trigger AS $$
            BEGIN
                IF NEW.backtest_strategy_version_id IS DISTINCT FROM OLD.backtest_strategy_version_id
                   OR NEW.backtest_dataset_id IS DISTINCT FROM OLD.backtest_dataset_id
                   OR NEW.backtest_dataset_rs_run_id IS DISTINCT FROM OLD.backtest_dataset_rs_run_id
                   OR NEW.dataset_id IS DISTINCT FROM OLD.dataset_id
                   OR NEW.dataset_manifest_hash IS DISTINCT FROM OLD.dataset_manifest_hash
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
        op.execute("""
            CREATE FUNCTION backtest_prevent_terminal_result_mutation() RETURNS trigger AS $$
            DECLARE target_run_id integer;
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    target_run_id := OLD.backtest_run_id;
                ELSE
                    target_run_id := NEW.backtest_run_id;
                END IF;
                IF EXISTS (SELECT 1 FROM backtest_runs WHERE id = target_run_id
                           AND status IN ('cancelled', 'failed', 'data_unavailable', 'completed')) THEN
                    RAISE EXCEPTION 'terminal backtest results are immutable';
                END IF;
                IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
        """)
        for table in ("backtest_benchmark_snapshots", "backtest_daily_equity", "backtest_orders", "backtest_trades"):
            op.execute(
                f"CREATE TRIGGER trg_{table}_terminal_immutable "
                f"BEFORE INSERT OR UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION backtest_prevent_terminal_result_mutation()"
            )
        op.execute("""
            CREATE FUNCTION backtest_prevent_terminal_benchmark_price_mutation() RETURNS trigger AS $$
            DECLARE target_snapshot_id integer;
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    target_snapshot_id := OLD.backtest_benchmark_snapshot_id;
                ELSE
                    target_snapshot_id := NEW.backtest_benchmark_snapshot_id;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM backtest_benchmark_snapshots snapshot
                    JOIN backtest_runs run ON run.id = snapshot.backtest_run_id
                    WHERE snapshot.id = target_snapshot_id
                      AND run.status IN ('cancelled', 'failed', 'data_unavailable', 'completed')
                ) THEN
                    RAISE EXCEPTION 'terminal benchmark snapshots are immutable';
                END IF;
                IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER trg_backtest_benchmark_snapshot_prices_terminal_immutable
            BEFORE INSERT OR UPDATE OR DELETE ON backtest_benchmark_snapshot_prices
            FOR EACH ROW EXECUTE FUNCTION backtest_prevent_terminal_benchmark_price_mutation()
        """)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_backtest_benchmark_snapshot_prices_terminal_immutable ON backtest_benchmark_snapshot_prices")
        op.execute("DROP FUNCTION IF EXISTS backtest_prevent_terminal_benchmark_price_mutation()")
        for table in ("backtest_benchmark_snapshots", "backtest_daily_equity", "backtest_orders", "backtest_trades"):
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_terminal_immutable ON {table}")
        op.execute("DROP FUNCTION IF EXISTS backtest_prevent_terminal_result_mutation()")
        op.execute("DROP TRIGGER IF EXISTS trg_backtest_runs_transition ON backtest_runs")
        op.execute("DROP FUNCTION IF EXISTS backtest_enforce_run_transition()")
        op.execute("DROP TRIGGER IF EXISTS trg_backtest_strategy_versions_immutable ON backtest_strategy_versions")
        op.execute("DROP FUNCTION IF EXISTS backtest_prevent_strategy_version_change()")
    op.drop_table("backtest_operator_lockouts")
    op.drop_table("backtest_operator_login_attempts")
    op.drop_table("backtest_operator_sessions")
    op.drop_table("backtest_trades")
    op.drop_table("backtest_orders")
    op.drop_table("backtest_daily_equity")
    op.drop_table("backtest_benchmark_snapshot_prices")
    op.drop_table("backtest_benchmark_snapshots")
    op.drop_table("backtest_runs")
    op.drop_table("backtest_strategy_versions")
    op.drop_table("backtest_strategies")
