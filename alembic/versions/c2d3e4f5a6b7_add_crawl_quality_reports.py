"""Add immutable crawl quality reports for weekly analysis."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Local development may import the API before Alembic runs, causing
    # Base.metadata.create_all() to materialize this table.  Treat that
    # equivalent schema as already created so a later container migration can
    # advance the revision instead of crash-looping on DuplicateTable.
    if "crawl_quality_reports" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "crawl_quality_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("crawl_job_id", sa.Integer(), nullable=False),
        sa.Column("report_schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("trade_date", sa.Date(), nullable=True),
        sa.Column("job_type", sa.String(length=50), nullable=False),
        sa.Column("job_status", sa.String(length=30), nullable=False),
        sa.Column("symbols_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("symbols_succeeded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("symbols_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("coverage_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("error_distribution", sa.JSON(), nullable=False),
        sa.Column("repeated_failure_summary", sa.JSON(), nullable=False),
        sa.Column("anomaly_summary", sa.JSON(), nullable=False),
        sa.Column("sample_refs", sa.JSON(), nullable=False),
        sa.Column("source_snapshot", sa.JSON(), nullable=False),
        sa.Column("report_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["crawl_job_id"], ["crawl_jobs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("crawl_job_id", name="uq_crawl_quality_reports_crawl_job_id"),
        sa.UniqueConstraint("report_hash", name="uq_crawl_quality_reports_report_hash"),
        sa.CheckConstraint("symbols_total >= 0", name="ck_crawl_quality_reports_symbols_total"),
        sa.CheckConstraint("symbols_succeeded >= 0", name="ck_crawl_quality_reports_symbols_succeeded"),
        sa.CheckConstraint("symbols_failed >= 0", name="ck_crawl_quality_reports_symbols_failed"),
        sa.CheckConstraint("failure_event_count >= 0", name="ck_crawl_quality_reports_failure_events"),
    )
    op.create_index("ix_crawl_quality_reports_trade_date", "crawl_quality_reports", ["trade_date"])
    op.create_index("ix_crawl_quality_reports_job_type", "crawl_quality_reports", ["job_type"])
    op.create_index("ix_crawl_quality_reports_job_status", "crawl_quality_reports", ["job_status"])


def downgrade() -> None:
    op.drop_index("ix_crawl_quality_reports_job_status", table_name="crawl_quality_reports")
    op.drop_index("ix_crawl_quality_reports_job_type", table_name="crawl_quality_reports")
    op.drop_index("ix_crawl_quality_reports_trade_date", table_name="crawl_quality_reports")
    op.drop_table("crawl_quality_reports")
