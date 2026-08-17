"""Add PostgreSQL-backed Kiwoom repair queue tables."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "8c6d4e2f1a03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "crawl_repair_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("crawl_target_result_id", sa.Integer(), nullable=True),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("history_from", sa.Date(), nullable=True),
        sa.Column("operation", sa.String(length=40), nullable=False, server_default="daily_chart"),
        sa.Column("error_type", sa.String(length=80), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False, server_default="kiwoom"),
        sa.Column("adjusted_price", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column(
            "application_status",
            sa.String(length=20),
            nullable=False,
            server_default="not_applied",
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("claimed_by", sa.String(length=100), nullable=True),
        sa.Column("claim_token_hash", sa.String(length=64), nullable=True),
        sa.Column("claim_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("last_http_status", sa.Integer(), nullable=True),
        sa.Column("application_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["job_id"], ["crawl_jobs.id"]),
        sa.ForeignKeyConstraint(["crawl_target_result_id"], ["crawl_target_results.id"]),
        sa.UniqueConstraint("dedupe_key", name="uq_crawl_repair_requests_dedupe_key"),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'expired', 'cancelled')",
            name="ck_crawl_repair_requests_status",
        ),
        sa.CheckConstraint(
            "application_status IN ('not_applied', 'applied', 'conflict', 'rejected')",
            name="ck_crawl_repair_requests_application_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_crawl_repair_requests_attempt_count"),
        sa.CheckConstraint("max_attempts > 0", name="ck_crawl_repair_requests_max_attempts"),
    )
    op.create_index("ix_crawl_repair_requests_dedupe_key", "crawl_repair_requests", ["dedupe_key"])
    op.create_index("ix_crawl_repair_requests_job_id", "crawl_repair_requests", ["job_id"])
    op.create_index(
        "ix_crawl_repair_requests_crawl_target_result_id",
        "crawl_repair_requests",
        ["crawl_target_result_id"],
    )
    op.create_index("ix_crawl_repair_requests_symbol", "crawl_repair_requests", ["symbol"])
    op.create_index("ix_crawl_repair_requests_trade_date", "crawl_repair_requests", ["trade_date"])
    op.create_index("ix_crawl_repair_requests_error_type", "crawl_repair_requests", ["error_type"])
    op.create_index("ix_crawl_repair_requests_status", "crawl_repair_requests", ["status"])
    op.create_index("ix_crawl_repair_requests_application_status", "crawl_repair_requests", ["application_status"])
    op.create_index("ix_crawl_repair_requests_next_attempt_at", "crawl_repair_requests", ["next_attempt_at"])
    op.create_index("ix_crawl_repair_requests_claim_token_hash", "crawl_repair_requests", ["claim_token_hash"])
    op.create_index(
        "ix_crawl_repair_requests_ready",
        "crawl_repair_requests",
        ["status", "next_attempt_at", "requested_at"],
    )
    op.create_index(
        "ix_crawl_repair_requests_lease",
        "crawl_repair_requests",
        ["status", "lease_expires_at"],
    )

    op.create_table(
        "crawl_repair_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("executor", sa.String(length=50), nullable=False, server_default="sam"),
        sa.Column("tool", sa.String(length=100), nullable=True),
        sa.Column("mode", sa.String(length=30), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="processing"),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latest_date", sa.Date(), nullable=True),
        sa.Column("data_complete", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("result_hash", sa.String(length=64), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["request_id"], ["crawl_repair_requests.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("request_id", "attempt_no", name="uq_crawl_repair_attempt_request_no"),
        sa.CheckConstraint(
            "status IN ('processing', 'completed', 'failed')",
            name="ck_crawl_repair_attempts_status",
        ),
        sa.CheckConstraint("row_count >= 0", name="ck_crawl_repair_attempts_row_count"),
    )
    op.create_index("ix_crawl_repair_attempts_request_id", "crawl_repair_attempts", ["request_id"])
    op.create_index(
        "ix_crawl_repair_attempts_request_status",
        "crawl_repair_attempts",
        ["request_id", "status"],
    )

    op.create_table(
        "crawl_repair_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="kiwoom"),
        sa.Column("adjusted_price", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("open", sa.Numeric(18, 4), nullable=False),
        sa.Column("high", sa.Numeric(18, 4), nullable=False),
        sa.Column("low", sa.Numeric(18, 4), nullable=False),
        sa.Column("close", sa.Numeric(18, 4), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("change_rate", sa.Numeric(10, 4), nullable=True),
        sa.Column("application_status", sa.String(length=20), nullable=False, server_default="not_applied"),
        sa.Column("application_error", sa.Text(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["request_id"], ["crawl_repair_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attempt_id"], ["crawl_repair_attempts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "request_id",
            "attempt_id",
            "symbol",
            "trade_date",
            name="uq_crawl_repair_results_attempt_symbol_date",
        ),
        sa.CheckConstraint("open > 0", name="ck_crawl_repair_results_open_positive"),
        sa.CheckConstraint("high > 0", name="ck_crawl_repair_results_high_positive"),
        sa.CheckConstraint("low > 0", name="ck_crawl_repair_results_low_positive"),
        sa.CheckConstraint("close > 0", name="ck_crawl_repair_results_close_positive"),
        sa.CheckConstraint("volume >= 0", name="ck_crawl_repair_results_volume_nonnegative"),
        sa.CheckConstraint("high >= low", name="ck_crawl_repair_results_high_low"),
        sa.CheckConstraint("high >= open AND high >= close", name="ck_crawl_repair_results_high_bound"),
        sa.CheckConstraint("low <= open AND low <= close", name="ck_crawl_repair_results_low_bound"),
        sa.CheckConstraint(
            "application_status IN ('not_applied', 'applied', 'conflict', 'rejected')",
            name="ck_crawl_repair_results_application_status",
        ),
    )
    op.create_index("ix_crawl_repair_results_request_id", "crawl_repair_results", ["request_id"])
    op.create_index("ix_crawl_repair_results_attempt_id", "crawl_repair_results", ["attempt_id"])
    op.create_index("ix_crawl_repair_results_symbol", "crawl_repair_results", ["symbol"])
    op.create_index("ix_crawl_repair_results_trade_date", "crawl_repair_results", ["trade_date"])
    op.create_index("ix_crawl_repair_results_application_status", "crawl_repair_results", ["application_status"])
    op.create_index(
        "ix_crawl_repair_results_request_date",
        "crawl_repair_results",
        ["request_id", "trade_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_crawl_repair_results_request_date", table_name="crawl_repair_results")
    op.drop_index("ix_crawl_repair_results_application_status", table_name="crawl_repair_results")
    op.drop_index("ix_crawl_repair_results_trade_date", table_name="crawl_repair_results")
    op.drop_index("ix_crawl_repair_results_symbol", table_name="crawl_repair_results")
    op.drop_index("ix_crawl_repair_results_attempt_id", table_name="crawl_repair_results")
    op.drop_index("ix_crawl_repair_results_request_id", table_name="crawl_repair_results")
    op.drop_table("crawl_repair_results")

    op.drop_index("ix_crawl_repair_attempts_request_status", table_name="crawl_repair_attempts")
    op.drop_index("ix_crawl_repair_attempts_request_id", table_name="crawl_repair_attempts")
    op.drop_table("crawl_repair_attempts")

    op.drop_index("ix_crawl_repair_requests_lease", table_name="crawl_repair_requests")
    op.drop_index("ix_crawl_repair_requests_ready", table_name="crawl_repair_requests")
    op.drop_index("ix_crawl_repair_requests_claim_token_hash", table_name="crawl_repair_requests")
    op.drop_index("ix_crawl_repair_requests_next_attempt_at", table_name="crawl_repair_requests")
    op.drop_index("ix_crawl_repair_requests_application_status", table_name="crawl_repair_requests")
    op.drop_index("ix_crawl_repair_requests_status", table_name="crawl_repair_requests")
    op.drop_index("ix_crawl_repair_requests_error_type", table_name="crawl_repair_requests")
    op.drop_index("ix_crawl_repair_requests_trade_date", table_name="crawl_repair_requests")
    op.drop_index("ix_crawl_repair_requests_symbol", table_name="crawl_repair_requests")
    op.drop_index("ix_crawl_repair_requests_crawl_target_result_id", table_name="crawl_repair_requests")
    op.drop_index("ix_crawl_repair_requests_job_id", table_name="crawl_repair_requests")
    op.drop_index("ix_crawl_repair_requests_dedupe_key", table_name="crawl_repair_requests")
    op.drop_table("crawl_repair_requests")
