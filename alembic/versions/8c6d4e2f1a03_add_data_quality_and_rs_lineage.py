"""Add data-quality audit, observation and RS lineage tables.

Revision ID: 8c6d4e2f1a03
Revises: 7b5f3a1c9d22
Create Date: 2026-08-11 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8c6d4e2f1a03"
down_revision: Union[str, Sequence[str], None] = "7b5f3a1c9d22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Local development uses ``Base.metadata.create_all`` during API startup.
    # If that already materialized this revision's tables before Alembic is
    # run, preserve the data and only finish the view creation; production
    # databases still take the normal create-table path below.
    inspector = sa.inspect(op.get_bind())
    if "validation_runs" in inspector.get_table_names():
        rs_score_columns = {
            column["name"] for column in inspector.get_columns("rs_scores")
        }
        if "rs_run_id" not in rs_score_columns:
            op.add_column(
                "rs_scores",
                sa.Column("rs_run_id", sa.Integer(), nullable=True),
            )
        rs_score_indexes = {
            index["name"] for index in inspector.get_indexes("rs_scores")
        }
        if "ix_rs_scores_rs_run_id" not in rs_score_indexes:
            op.create_index("ix_rs_scores_rs_run_id", "rs_scores", ["rs_run_id"])
        rs_score_foreign_keys = {
            tuple(foreign_key.get("constrained_columns", []))
            for foreign_key in inspector.get_foreign_keys("rs_scores")
        }
        if ("rs_run_id",) not in rs_score_foreign_keys:
            op.create_foreign_key(
                "fk_rs_scores_rs_run_id",
                "rs_scores",
                "rs_runs",
                ["rs_run_id"],
                ["id"],
            )
        _create_views()
        return

    op.create_table(
        "validation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("crawl_job_id", sa.Integer(), nullable=True),
        sa.Column("trade_date", sa.Date(), nullable=True),
        sa.Column("run_kind", sa.String(length=30), nullable=False),
        sa.Column("validator_version", sa.String(length=50), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("expected_symbols", sa.Integer(), nullable=False),
        sa.Column("fresh_symbols", sa.Integer(), nullable=False),
        sa.Column("stale_symbols", sa.Integer(), nullable=False),
        sa.Column("rs_candidate_symbols", sa.Integer(), nullable=False),
        sa.Column("pass_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("critical_count", sa.Integer(), nullable=False),
        sa.Column("coverage_rate", sa.Numeric(8, 6), nullable=False),
        sa.Column("rs_fresh_input_coverage_rate", sa.Numeric(8, 6), nullable=False),
        sa.Column("validation_status", sa.String(length=30), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["crawl_job_id"], ["crawl_jobs.id"]),
    )
    op.create_index("ix_validation_runs_crawl_job_id", "validation_runs", ["crawl_job_id"])
    op.create_index("ix_validation_runs_trade_date", "validation_runs", ["trade_date"])
    op.create_index("ix_validation_runs_status", "validation_runs", ["validation_status"])
    op.create_index(
        "ix_validation_runs_job_trade_date",
        "validation_runs",
        ["crawl_job_id", "trade_date"],
    )

    op.create_table(
        "validation_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("validation_run_id", sa.Integer(), nullable=False),
        sa.Column("subject_type", sa.String(length=30), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=True),
        sa.Column("benchmark_id", sa.Integer(), nullable=True),
        sa.Column("target_key", sa.String(length=255), nullable=True),
        sa.Column("trade_date", sa.Date(), nullable=True),
        sa.Column("rule_id", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=False),
        sa.Column("case_status", sa.String(length=30), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=True),
        sa.Column("confidence", sa.Numeric(8, 6), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("validator_version", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["validation_run_id"], ["validation_runs.id"]),
        sa.ForeignKeyConstraint(["symbol_id"], ["symbols.id"]),
        sa.ForeignKeyConstraint(["benchmark_id"], ["benchmarks.id"]),
    )
    op.create_index("ix_validation_cases_validation_run_id", "validation_cases", ["validation_run_id"])
    op.create_index("ix_validation_cases_symbol_id", "validation_cases", ["symbol_id"])
    op.create_index("ix_validation_cases_benchmark_id", "validation_cases", ["benchmark_id"])
    op.create_index("ix_validation_cases_target_key", "validation_cases", ["target_key"])
    op.create_index("ix_validation_cases_trade_date", "validation_cases", ["trade_date"])
    op.create_index("ix_validation_cases_rule_id", "validation_cases", ["rule_id"])
    op.create_index("ix_validation_cases_severity", "validation_cases", ["severity"])
    op.create_index("ix_validation_cases_case_status", "validation_cases", ["case_status"])
    op.create_index(
        "ix_validation_cases_run_severity",
        "validation_cases",
        ["validation_run_id", "severity"],
    )
    op.create_index(
        "ix_validation_cases_subject",
        "validation_cases",
        ["subject_type", "symbol_id", "trade_date"],
    )
    op.create_index(
        "ix_validation_cases_rule_reason",
        "validation_cases",
        ["rule_id", "reason_code"],
    )

    for table_name, fk_column, fk_target in (
        ("price_observations", "symbol_id", "symbols.id"),
        ("benchmark_observations", "benchmark_id", "benchmarks.id"),
    ):
        if table_name == "price_observations":
            columns = [
                sa.Column("id", sa.Integer(), primary_key=True),
                sa.Column("symbol_id", sa.Integer(), nullable=False),
                sa.Column("crawl_job_id", sa.Integer(), nullable=True),
                sa.Column("trade_date", sa.Date(), nullable=False),
                sa.Column("open", sa.Numeric(18, 4), nullable=False),
                sa.Column("high", sa.Numeric(18, 4), nullable=False),
                sa.Column("low", sa.Numeric(18, 4), nullable=False),
                sa.Column("close", sa.Numeric(18, 4), nullable=False),
                sa.Column("volume", sa.BigInteger(), nullable=False),
                sa.Column("change_rate", sa.Numeric(10, 4), nullable=False),
                sa.Column("provider", sa.String(100), nullable=False),
                sa.Column("parser_version", sa.String(50), nullable=True),
                sa.Column("payload_hash", sa.String(64), nullable=False),
                sa.Column("observed_at", sa.DateTime(), nullable=False),
                sa.Column("metadata", sa.JSON(), nullable=False),
                sa.Column("created_at", sa.DateTime(), nullable=False),
                sa.ForeignKeyConstraint(["symbol_id"], [fk_target]),
                sa.ForeignKeyConstraint(["crawl_job_id"], ["crawl_jobs.id"]),
            ]
        else:
            columns = [
                sa.Column("id", sa.Integer(), primary_key=True),
                sa.Column("benchmark_id", sa.Integer(), nullable=False),
                sa.Column("crawl_job_id", sa.Integer(), nullable=True),
                sa.Column("trade_date", sa.Date(), nullable=False),
                sa.Column("open", sa.Numeric(18, 4), nullable=False),
                sa.Column("high", sa.Numeric(18, 4), nullable=False),
                sa.Column("low", sa.Numeric(18, 4), nullable=False),
                sa.Column("close", sa.Numeric(18, 4), nullable=False),
                sa.Column("volume", sa.BigInteger(), nullable=True),
                sa.Column("change_rate", sa.Numeric(10, 4), nullable=False),
                sa.Column("provider", sa.String(100), nullable=False),
                sa.Column("parser_version", sa.String(50), nullable=True),
                sa.Column("payload_hash", sa.String(64), nullable=False),
                sa.Column("observed_at", sa.DateTime(), nullable=False),
                sa.Column("metadata", sa.JSON(), nullable=False),
                sa.Column("created_at", sa.DateTime(), nullable=False),
                sa.ForeignKeyConstraint(["benchmark_id"], [fk_target]),
                sa.ForeignKeyConstraint(["crawl_job_id"], ["crawl_jobs.id"]),
            ]
        op.create_table(table_name, *columns)
        op.create_index(f"ix_{table_name}_{fk_column}", table_name, [fk_column])
        op.create_index(f"ix_{table_name}_trade_date", table_name, ["trade_date"])
        op.create_index(f"ix_{table_name}_crawl_job_id", table_name, ["crawl_job_id"])
        op.create_index(f"ix_{table_name}_payload_hash", table_name, ["payload_hash"])
        op.create_index(
            f"ix_{table_name}_{fk_column}_date",
            table_name,
            [fk_column, "trade_date"],
        )

    op.create_table(
        "ohlc_corrections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("field_name", sa.String(30), nullable=False),
        sa.Column("original_value", sa.JSON(), nullable=True),
        sa.Column("corrected_value", sa.JSON(), nullable=True),
        sa.Column("reason_code", sa.String(80), nullable=False),
        sa.Column("reference_source", sa.String(100), nullable=True),
        sa.Column("reference_value", sa.JSON(), nullable=True),
        sa.Column("validation_case_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["symbol_id"], ["symbols.id"]),
        sa.ForeignKeyConstraint(["validation_case_id"], ["validation_cases.id"]),
    )
    op.create_index("ix_ohlc_corrections_symbol_id", "ohlc_corrections", ["symbol_id"])
    op.create_index("ix_ohlc_corrections_trade_date", "ohlc_corrections", ["trade_date"])
    op.create_index("ix_ohlc_corrections_validation_case_id", "ohlc_corrections", ["validation_case_id"])
    op.create_index("ix_ohlc_corrections_status", "ohlc_corrections", ["status"])
    op.create_index(
        "ix_ohlc_corrections_symbol_date",
        "ohlc_corrections",
        ["symbol_id", "trade_date"],
    )

    op.create_table(
        "ohlc_exclusions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=False),
        sa.Column("validation_case_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["symbol_id"], ["symbols.id"]),
        sa.ForeignKeyConstraint(["validation_case_id"], ["validation_cases.id"]),
        sa.UniqueConstraint("symbol_id", "trade_date", name="uq_ohlc_exclusions_symbol_date"),
    )
    op.create_index("ix_ohlc_exclusions_symbol_id", "ohlc_exclusions", ["symbol_id"])
    op.create_index("ix_ohlc_exclusions_trade_date", "ohlc_exclusions", ["trade_date"])
    op.create_index("ix_ohlc_exclusions_validation_case_id", "ohlc_exclusions", ["validation_case_id"])
    op.create_index("ix_ohlc_exclusions_status", "ohlc_exclusions", ["status"])

    op.create_table(
        "corporate_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("ratio", sa.Numeric(18, 8), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("validation_case_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["symbol_id"], ["symbols.id"]),
        sa.ForeignKeyConstraint(["validation_case_id"], ["validation_cases.id"]),
    )
    op.create_index("ix_corporate_actions_symbol_id", "corporate_actions", ["symbol_id"])
    op.create_index("ix_corporate_actions_event_date", "corporate_actions", ["event_date"])
    op.create_index("ix_corporate_actions_validation_case_id", "corporate_actions", ["validation_case_id"])
    op.create_index(
        "ix_corporate_actions_symbol_date",
        "corporate_actions",
        ["symbol_id", "event_date"],
    )

    op.create_table(
        "rs_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("validation_run_id", sa.Integer(), nullable=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("input_policy_version", sa.String(50), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("symbol_count", sa.Integer(), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["validation_run_id"], ["validation_runs.id"]),
    )
    op.create_index("ix_rs_runs_validation_run_id", "rs_runs", ["validation_run_id"])
    op.create_index("ix_rs_runs_trade_date", "rs_runs", ["trade_date"])
    op.create_index("ix_rs_runs_status", "rs_runs", ["status"])
    op.create_index("ix_rs_runs_trade_status", "rs_runs", ["trade_date", "status"])

    op.create_table(
        "rs_input_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rs_run_id", sa.Integer(), nullable=False),
        sa.Column("symbol_id", sa.Integer(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("input_trade_date", sa.Date(), nullable=True),
        sa.Column("stale_lag_days", sa.Integer(), nullable=True),
        sa.Column("input_status", sa.String(30), nullable=False),
        sa.Column("price_row_count", sa.Integer(), nullable=False),
        sa.Column("price_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["rs_run_id"], ["rs_runs.id"]),
        sa.ForeignKeyConstraint(["symbol_id"], ["symbols.id"]),
        sa.UniqueConstraint("rs_run_id", "symbol_id", name="uq_rs_input_snapshot_run_symbol"),
    )
    op.create_index("ix_rs_input_snapshots_rs_run_id", "rs_input_snapshots", ["rs_run_id"])
    op.create_index("ix_rs_input_snapshots_symbol_id", "rs_input_snapshots", ["symbol_id"])
    op.create_index("ix_rs_input_snapshots_target_date", "rs_input_snapshots", ["target_date"])

    op.add_column(
        "rs_scores",
        sa.Column("rs_run_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_rs_scores_rs_run_id",
        "rs_scores",
        "rs_runs",
        ["rs_run_id"],
        ["id"],
    )
    op.create_index("ix_rs_scores_rs_run_id", "rs_scores", ["rs_run_id"])

    _create_views()


def _create_views() -> None:
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE VIEW v_daily_prices_validated AS
            SELECT
                dp.id,
                dp.symbol_id,
                s.code,
                s.market,
                dp.trade_date,
                COALESCE((SELECT (CASE WHEN json_typeof(oc.corrected_value) = 'object'
                                       THEN oc.corrected_value ->> 'value'
                                       ELSE oc.corrected_value #>> '{}'
                                  END)::numeric(18,4)
                          FROM ohlc_corrections oc
                          WHERE oc.symbol_id = dp.symbol_id
                            AND oc.trade_date = dp.trade_date
                            AND oc.field_name = 'open'
                            AND oc.status = 'APPROVED'
                          ORDER BY oc.id DESC LIMIT 1), dp.open) AS open,
                COALESCE((SELECT (CASE WHEN json_typeof(oc.corrected_value) = 'object'
                                       THEN oc.corrected_value ->> 'value'
                                       ELSE oc.corrected_value #>> '{}'
                                  END)::numeric(18,4)
                          FROM ohlc_corrections oc
                          WHERE oc.symbol_id = dp.symbol_id
                            AND oc.trade_date = dp.trade_date
                            AND oc.field_name = 'high'
                            AND oc.status = 'APPROVED'
                          ORDER BY oc.id DESC LIMIT 1), dp.high) AS high,
                COALESCE((SELECT (CASE WHEN json_typeof(oc.corrected_value) = 'object'
                                       THEN oc.corrected_value ->> 'value'
                                       ELSE oc.corrected_value #>> '{}'
                                  END)::numeric(18,4)
                          FROM ohlc_corrections oc
                          WHERE oc.symbol_id = dp.symbol_id
                            AND oc.trade_date = dp.trade_date
                            AND oc.field_name = 'low'
                            AND oc.status = 'APPROVED'
                          ORDER BY oc.id DESC LIMIT 1), dp.low) AS low,
                COALESCE((SELECT (CASE WHEN json_typeof(oc.corrected_value) = 'object'
                                       THEN oc.corrected_value ->> 'value'
                                       ELSE oc.corrected_value #>> '{}'
                                  END)::numeric(18,4)
                          FROM ohlc_corrections oc
                          WHERE oc.symbol_id = dp.symbol_id
                            AND oc.trade_date = dp.trade_date
                            AND oc.field_name = 'close'
                            AND oc.status = 'APPROVED'
                          ORDER BY oc.id DESC LIMIT 1), dp.close) AS close,
                COALESCE((SELECT (CASE WHEN json_typeof(oc.corrected_value) = 'object'
                                       THEN oc.corrected_value ->> 'value'
                                       ELSE oc.corrected_value #>> '{}'
                                  END)::bigint
                          FROM ohlc_corrections oc
                          WHERE oc.symbol_id = dp.symbol_id
                            AND oc.trade_date = dp.trade_date
                            AND oc.field_name = 'volume'
                            AND oc.status = 'APPROVED'
                          ORDER BY oc.id DESC LIMIT 1), dp.volume) AS volume,
                COALESCE((SELECT (CASE WHEN json_typeof(oc.corrected_value) = 'object'
                                       THEN oc.corrected_value ->> 'value'
                                       ELSE oc.corrected_value #>> '{}'
                                  END)::numeric(10,4)
                          FROM ohlc_corrections oc
                          WHERE oc.symbol_id = dp.symbol_id
                            AND oc.trade_date = dp.trade_date
                            AND oc.field_name = 'change_rate'
                            AND oc.status = 'APPROVED'
                          ORDER BY oc.id DESC LIMIT 1), dp.change_rate) AS change_rate,
                dp.source,
                dp.created_at
            FROM daily_prices dp
            JOIN symbols s ON s.id = dp.symbol_id
            WHERE NOT EXISTS (
                SELECT 1
                FROM ohlc_exclusions oe
                WHERE oe.symbol_id = dp.symbol_id
                  AND oe.trade_date = dp.trade_date
                  AND oe.status = 'APPROVED'
            )
            AND NOT EXISTS (
                SELECT 1
                FROM validation_cases vc
                WHERE vc.subject_type = 'daily_price'
                  AND vc.symbol_id = dp.symbol_id
                  AND vc.trade_date = dp.trade_date
                  AND vc.decision = 'EXCLUDE'
                  AND vc.case_status IN ('auto_resolved', 'approved')
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE VIEW v_rs_input_prices AS
            SELECT * FROM v_daily_prices_validated
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP VIEW IF EXISTS v_rs_input_prices"))
    op.execute(sa.text("DROP VIEW IF EXISTS v_daily_prices_validated"))
    op.drop_index("ix_rs_scores_rs_run_id", table_name="rs_scores")
    op.drop_constraint("fk_rs_scores_rs_run_id", "rs_scores", type_="foreignkey")
    op.drop_column("rs_scores", "rs_run_id")
    op.drop_index("ix_rs_input_snapshots_target_date", table_name="rs_input_snapshots")
    op.drop_index("ix_rs_input_snapshots_symbol_id", table_name="rs_input_snapshots")
    op.drop_index("ix_rs_input_snapshots_rs_run_id", table_name="rs_input_snapshots")
    op.drop_table("rs_input_snapshots")
    op.drop_index("ix_rs_runs_trade_status", table_name="rs_runs")
    op.drop_index("ix_rs_runs_status", table_name="rs_runs")
    op.drop_index("ix_rs_runs_trade_date", table_name="rs_runs")
    op.drop_index("ix_rs_runs_validation_run_id", table_name="rs_runs")
    op.drop_table("rs_runs")
    op.drop_index("ix_corporate_actions_symbol_date", table_name="corporate_actions")
    op.drop_index("ix_corporate_actions_validation_case_id", table_name="corporate_actions")
    op.drop_index("ix_corporate_actions_event_date", table_name="corporate_actions")
    op.drop_index("ix_corporate_actions_symbol_id", table_name="corporate_actions")
    op.drop_table("corporate_actions")
    op.drop_index("ix_ohlc_exclusions_status", table_name="ohlc_exclusions")
    op.drop_index("ix_ohlc_exclusions_validation_case_id", table_name="ohlc_exclusions")
    op.drop_index("ix_ohlc_exclusions_trade_date", table_name="ohlc_exclusions")
    op.drop_index("ix_ohlc_exclusions_symbol_id", table_name="ohlc_exclusions")
    op.drop_table("ohlc_exclusions")
    op.drop_index("ix_ohlc_corrections_symbol_date", table_name="ohlc_corrections")
    op.drop_index("ix_ohlc_corrections_status", table_name="ohlc_corrections")
    op.drop_index("ix_ohlc_corrections_validation_case_id", table_name="ohlc_corrections")
    op.drop_index("ix_ohlc_corrections_trade_date", table_name="ohlc_corrections")
    op.drop_index("ix_ohlc_corrections_symbol_id", table_name="ohlc_corrections")
    op.drop_table("ohlc_corrections")
    for table_name, fk_column in (
        ("benchmark_observations", "benchmark_id"),
        ("price_observations", "symbol_id"),
    ):
        op.drop_index(f"ix_{table_name}_{fk_column}_date", table_name=table_name)
        op.drop_index(f"ix_{table_name}_payload_hash", table_name=table_name)
        op.drop_index(f"ix_{table_name}_crawl_job_id", table_name=table_name)
        op.drop_index(f"ix_{table_name}_trade_date", table_name=table_name)
        op.drop_index(f"ix_{table_name}_{fk_column}", table_name=table_name)
        op.drop_table(table_name)
    op.drop_index("ix_validation_cases_rule_reason", table_name="validation_cases")
    op.drop_index("ix_validation_cases_subject", table_name="validation_cases")
    op.drop_index("ix_validation_cases_run_severity", table_name="validation_cases")
    op.drop_index("ix_validation_cases_case_status", table_name="validation_cases")
    op.drop_index("ix_validation_cases_severity", table_name="validation_cases")
    op.drop_index("ix_validation_cases_rule_id", table_name="validation_cases")
    op.drop_index("ix_validation_cases_trade_date", table_name="validation_cases")
    op.drop_index("ix_validation_cases_target_key", table_name="validation_cases")
    op.drop_index("ix_validation_cases_benchmark_id", table_name="validation_cases")
    op.drop_index("ix_validation_cases_symbol_id", table_name="validation_cases")
    op.drop_index("ix_validation_cases_validation_run_id", table_name="validation_cases")
    op.drop_table("validation_cases")
    op.drop_index("ix_validation_runs_job_trade_date", table_name="validation_runs")
    op.drop_index("ix_validation_runs_status", table_name="validation_runs")
    op.drop_index("ix_validation_runs_trade_date", table_name="validation_runs")
    op.drop_index("ix_validation_runs_crawl_job_id", table_name="validation_runs")
    op.drop_table("validation_runs")
