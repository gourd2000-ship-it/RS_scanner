"""Enforce complete EMA run artifacts and same-series generation parents.

Revision ID: x5b6c7d8e9f0
Revises: w4a5b6c7d8e9
"""

from collections.abc import Sequence

from alembic import op

revision: str = "x5b6c7d8e9f0"
down_revision: str | Sequence[str] | None = "w4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("indicator_generations") as batch:
            batch.create_foreign_key(
                "fk_indicator_generation_parent_series",
                "indicator_generations",
                ["parent_generation_id", "series_id"],
                ["id", "series_id"],
            )
    else:
        op.create_foreign_key(
            "fk_indicator_generation_parent_series",
            "indicator_generations",
            "indicator_generations",
            ["parent_generation_id", "series_id"],
            ["id", "series_id"],
        )

    if bind.dialect.name == "postgresql":
        _replace_run_immutability_trigger()


def _replace_run_immutability_trigger() -> None:
    op.execute("""
        CREATE FUNCTION indicator_require_complete_run_values(target_run_id integer) RETURNS void AS $$
        DECLARE missing_trade_date date;
        BEGIN
            SELECT input.trade_date INTO missing_trade_date
            FROM indicator_input_snapshots input
            WHERE input.calculation_run_id = target_run_id
              AND (
                  SELECT COUNT(*)
                  FROM indicator_values value
                  WHERE value.calculation_run_id = target_run_id
                    AND value.trade_date = input.trade_date
              ) <> 4
            LIMIT 1;
            IF missing_trade_date IS NOT NULL THEN
                RAISE EXCEPTION
                    'completed indicator run % is missing one or more EMA periods for %',
                    target_run_id, missing_trade_date;
            END IF;

            IF EXISTS (
                SELECT 1
                FROM indicator_values value
                WHERE value.calculation_run_id = target_run_id
                  AND NOT EXISTS (
                      SELECT 1
                      FROM indicator_input_snapshots input
                      WHERE input.calculation_run_id = target_run_id
                        AND input.trade_date = value.trade_date
                  )
            ) THEN
                RAISE EXCEPTION
                    'completed indicator run % has EMA values without an input snapshot',
                    target_run_id;
            END IF;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_indicator_runs_completed_immutable ON indicator_calculation_runs")
    op.execute("""
        CREATE OR REPLACE FUNCTION indicator_prevent_completed_run_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.status = 'completed' THEN
                    PERFORM indicator_require_complete_run_values(NEW.id);
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.status = 'completed' THEN
                RAISE EXCEPTION 'completed indicator calculation runs are immutable';
            END IF;
            IF TG_OP = 'UPDATE' AND NEW.status = 'completed' THEN
                PERFORM indicator_require_complete_run_values(NEW.id);
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_indicator_runs_completed_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON indicator_calculation_runs
        FOR EACH ROW EXECUTE FUNCTION indicator_prevent_completed_run_mutation()
    """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_indicator_runs_completed_immutable ON indicator_calculation_runs")
        op.execute("DROP FUNCTION IF EXISTS indicator_require_complete_run_values(integer)")
        op.execute("""
            CREATE OR REPLACE FUNCTION indicator_prevent_completed_run_mutation() RETURNS trigger AS $$
            BEGIN
                IF OLD.status = 'completed' THEN
                    RAISE EXCEPTION 'completed indicator calculation runs are immutable';
                END IF;
                RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
            END;
            $$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER trg_indicator_runs_completed_immutable
            BEFORE UPDATE OR DELETE ON indicator_calculation_runs
            FOR EACH ROW EXECUTE FUNCTION indicator_prevent_completed_run_mutation()
        """)

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("indicator_generations") as batch:
            batch.drop_constraint("fk_indicator_generation_parent_series", type_="foreignkey")
    else:
        op.drop_constraint(
            "fk_indicator_generation_parent_series",
            "indicator_generations",
            type_="foreignkey",
        )
