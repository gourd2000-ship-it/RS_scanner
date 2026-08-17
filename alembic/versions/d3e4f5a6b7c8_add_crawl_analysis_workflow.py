"""Add explicit Sam crawl-quality analysis requests and reports."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, Sequence[str], None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())
    analysis_tables = {
        "crawl_analysis_requests",
        "crawl_analysis_request_quality_reports",
        "crawl_analysis_reports",
    }
    if analysis_tables & existing_tables and not analysis_tables <= existing_tables:
        raise RuntimeError("partial crawl analysis schema exists; migration cannot safely continue")
    if not analysis_tables <= existing_tables:
        op.create_table(
        "crawl_analysis_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("requested_by", sa.String(length=100), nullable=False),
        sa.Column("request_kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="requested"),
        sa.Column("period_from", sa.Date(), nullable=False),
        sa.Column("period_to", sa.Date(), nullable=False),
        sa.Column("completed_job_ids", sa.JSON(), nullable=False),
        sa.Column("error_types", sa.JSON(), nullable=False),
        sa.Column("markets", sa.JSON(), nullable=False),
        sa.Column("sample_limit", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("accepted_by", sa.String(length=100), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("request_id", name="uq_crawl_analysis_requests_request_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_crawl_analysis_requests_idempotency_key"),
        sa.CheckConstraint("request_kind IN ('weekly', 'ad_hoc')", name="ck_crawl_analysis_requests_kind"),
        sa.CheckConstraint("status IN ('requested', 'accepted', 'report_ready', 'codex_reviewed', 'implemented', 'partially_implemented', 'deferred')", name="ck_crawl_analysis_requests_status"),
        sa.CheckConstraint("sample_limit >= 1 AND sample_limit <= 10", name="ck_crawl_analysis_requests_sample_limit"),
        sa.CheckConstraint("period_from <= period_to", name="ck_crawl_analysis_requests_period"),
        )
        op.create_index("ix_crawl_analysis_requests_request_id", "crawl_analysis_requests", ["request_id"])
        op.create_index("ix_crawl_analysis_requests_idempotency_key", "crawl_analysis_requests", ["idempotency_key"])
        op.create_index("ix_crawl_analysis_requests_request_kind", "crawl_analysis_requests", ["request_kind"])
        op.create_index("ix_crawl_analysis_requests_status", "crawl_analysis_requests", ["status"])

        op.create_table(
        "crawl_analysis_request_quality_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("analysis_request_id", sa.Integer(), nullable=False),
        sa.Column("quality_report_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["analysis_request_id"], ["crawl_analysis_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["quality_report_id"], ["crawl_quality_reports.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("analysis_request_id", "quality_report_id", name="uq_analysis_request_quality_report"),
        )
        op.create_index("ix_analysis_request_quality_reports_request", "crawl_analysis_request_quality_reports", ["analysis_request_id"])
        op.create_index("ix_analysis_request_quality_reports_report", "crawl_analysis_request_quality_reports", ["quality_report_id"])

        op.create_table(
        "crawl_analysis_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False, server_default="sam"),
        sa.Column("analysis_window", sa.JSON(), nullable=False),
        sa.Column("quality_report_refs", sa.JSON(), nullable=False),
        sa.Column("findings", sa.JSON(), nullable=False),
        sa.Column("kiwoom_evidence", sa.JSON(), nullable=False),
        sa.Column("recommendations", sa.JSON(), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=False),
        sa.Column("markdown_body", sa.Text(), nullable=False),
        sa.Column("report_json", sa.JSON(), nullable=False),
        sa.Column("report_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["request_id"], ["crawl_analysis_requests.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("request_id", name="uq_crawl_analysis_reports_request_id"),
        sa.UniqueConstraint("report_hash", name="uq_crawl_analysis_reports_report_hash"),
        )
        op.create_index("ix_crawl_analysis_reports_request_id", "crawl_analysis_reports", ["request_id"])

    # ``create_all`` honors unique constraints but the state-machine checks
    # live in Alembic.  Add any absent checks when the tables pre-existed.
    request_checks = {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_check_constraints("crawl_analysis_requests")
    }
    for name, condition in (
        ("ck_crawl_analysis_requests_kind", "request_kind IN ('weekly', 'ad_hoc')"),
        ("ck_crawl_analysis_requests_status", "status IN ('requested', 'accepted', 'report_ready', 'codex_reviewed', 'implemented', 'partially_implemented', 'deferred')"),
        ("ck_crawl_analysis_requests_sample_limit", "sample_limit >= 1 AND sample_limit <= 10"),
        ("ck_crawl_analysis_requests_period", "period_from <= period_to"),
    ):
        if name not in request_checks:
            op.create_check_constraint(name, "crawl_analysis_requests", condition)


def downgrade() -> None:
    op.drop_index("ix_crawl_analysis_reports_request_id", table_name="crawl_analysis_reports")
    op.drop_table("crawl_analysis_reports")
    op.drop_index("ix_analysis_request_quality_reports_report", table_name="crawl_analysis_request_quality_reports")
    op.drop_index("ix_analysis_request_quality_reports_request", table_name="crawl_analysis_request_quality_reports")
    op.drop_table("crawl_analysis_request_quality_reports")
    op.drop_index("ix_crawl_analysis_requests_status", table_name="crawl_analysis_requests")
    op.drop_index("ix_crawl_analysis_requests_request_kind", table_name="crawl_analysis_requests")
    op.drop_index("ix_crawl_analysis_requests_idempotency_key", table_name="crawl_analysis_requests")
    op.drop_index("ix_crawl_analysis_requests_request_id", table_name="crawl_analysis_requests")
    op.drop_table("crawl_analysis_requests")
