"""Add per-target crawl results and response byte metadata.

Revision ID: d31b0f6e7a21
Revises: 9b7d5e2c1a04
Create Date: 2026-08-11 00:00:00
"""

from typing import Sequence, Union

from alembic import context
from alembic import op
import sqlalchemy as sa


revision: str = "d31b0f6e7a21"
down_revision: Union[str, Sequence[str], None] = "9b7d5e2c1a04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    if context.is_offline_mode():
        return False
    return sa.inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    if context.is_offline_mode():
        return False
    return column in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if not _has_column("crawl_failures", "response_bytes"):
        op.add_column(
            "crawl_failures",
            sa.Column("response_bytes", sa.Integer(), nullable=True),
        )

    if _has_table("crawl_target_results"):
        # Development environments may have created the current ORM tables
        # before Alembic was run. Keep those tables and let later revisions
        # add only columns that are genuinely new.
        return

    op.create_table(
        "crawl_target_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("step_name", sa.String(length=50), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=False),
        sa.Column("target_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("rows_received", sa.Integer(), nullable=False),
        sa.Column("rows_persisted", sa.Integer(), nullable=False),
        sa.Column("latest_date_before", sa.Date(), nullable=True),
        sa.Column("latest_date_after", sa.Date(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("response_bytes", sa.Integer(), nullable=True),
        sa.Column("error_class", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["crawl_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "step_name",
            "target_key",
            name="uq_crawl_target_result_job_step_target",
        ),
    )
    op.create_index(op.f("ix_crawl_target_results_job_id"), "crawl_target_results", ["job_id"], unique=False)
    op.create_index(op.f("ix_crawl_target_results_step_name"), "crawl_target_results", ["step_name"], unique=False)
    op.create_index(op.f("ix_crawl_target_results_target_key"), "crawl_target_results", ["target_key"], unique=False)
    op.create_index(op.f("ix_crawl_target_results_status"), "crawl_target_results", ["status"], unique=False)
    op.create_index("ix_crawl_target_results_job_step", "crawl_target_results", ["job_id", "step_name"], unique=False)
    op.create_index("ix_crawl_target_results_job_status", "crawl_target_results", ["job_id", "status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_crawl_target_results_job_status", table_name="crawl_target_results")
    op.drop_index("ix_crawl_target_results_job_step", table_name="crawl_target_results")
    op.drop_index(op.f("ix_crawl_target_results_status"), table_name="crawl_target_results")
    op.drop_index(op.f("ix_crawl_target_results_target_key"), table_name="crawl_target_results")
    op.drop_index(op.f("ix_crawl_target_results_step_name"), table_name="crawl_target_results")
    op.drop_index(op.f("ix_crawl_target_results_job_id"), table_name="crawl_target_results")
    op.drop_table("crawl_target_results")
    op.drop_column("crawl_failures", "response_bytes")
