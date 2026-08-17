"""Add Codex audit records and freeze legacy repair work."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, Sequence[str], None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "codex_change_requests" not in inspector.get_table_names():
        op.create_table(
        "codex_change_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("change_request_id", sa.String(length=160), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("proposal_id", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="proposed"),
        sa.Column("requested_by", sa.String(length=100), nullable=False),
        sa.Column("approved_by", sa.String(length=100), nullable=True),
        sa.Column("target_files", sa.JSON(), nullable=False),
        sa.Column("change_scope", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.String(length=20), nullable=False),
        sa.Column("verification_plan", sa.JSON(), nullable=False),
        sa.Column("codex_run_id", sa.String(length=160), nullable=True),
        sa.Column("commit_ref", sa.String(length=160), nullable=True),
        sa.Column("test_results", sa.JSON(), nullable=False),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["report_id"], ["crawl_analysis_reports.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("change_request_id", name="uq_codex_change_requests_change_request_id"),
        sa.UniqueConstraint("report_id", "proposal_id", name="uq_codex_change_requests_report_proposal"),
        sa.CheckConstraint("status IN ('proposed', 'approved', 'running', 'verified', 'implemented', 'deferred', 'failed')", name="ck_codex_change_requests_status"),
        )
        op.create_index("ix_codex_change_requests_change_request_id", "codex_change_requests", ["change_request_id"])
        op.create_index("ix_codex_change_requests_report_id", "codex_change_requests", ["report_id"])
        op.create_index("ix_codex_change_requests_status", "codex_change_requests", ["status"])
    else:
        codex_checks = {
            item["name"]
            for item in sa.inspect(op.get_bind()).get_check_constraints("codex_change_requests")
        }
        if "ck_codex_change_requests_status" not in codex_checks:
            op.create_check_constraint(
                "ck_codex_change_requests_status",
                "codex_change_requests",
                "status IN ('proposed', 'approved', 'running', 'verified', 'implemented', 'deferred', 'failed')",
            )

    repair_checks = {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_check_constraints("crawl_repair_requests")
    }
    if "ck_crawl_repair_requests_status" in repair_checks:
        op.drop_constraint("ck_crawl_repair_requests_status", "crawl_repair_requests", type_="check")
    op.create_check_constraint(
        "ck_crawl_repair_requests_status",
        "crawl_repair_requests",
        "status IN ('pending', 'processing', 'completed', 'failed', 'expired', 'cancelled', 'legacy_hold')",
    )
    op.execute(
        "UPDATE crawl_repair_requests "
        "SET status = 'legacy_hold', claimed_by = NULL, claim_token_hash = NULL, "
        "lease_expires_at = NULL, last_error_code = 'workflow_superseded', "
        "last_error_message = 'legacy repair workflow superseded by weekly analysis', "
        "updated_at = CURRENT_TIMESTAMP "
        "WHERE status IN ('pending', 'processing')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_crawl_repair_requests_status", "crawl_repair_requests", type_="check")
    op.create_check_constraint(
        "ck_crawl_repair_requests_status",
        "crawl_repair_requests",
        "status IN ('pending', 'processing', 'completed', 'failed', 'expired', 'cancelled')",
    )
    op.drop_index("ix_codex_change_requests_status", table_name="codex_change_requests")
    op.drop_index("ix_codex_change_requests_report_id", table_name="codex_change_requests")
    op.drop_index("ix_codex_change_requests_change_request_id", table_name="codex_change_requests")
    op.drop_table("codex_change_requests")
