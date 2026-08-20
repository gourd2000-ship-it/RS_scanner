"""Auditable user-approved implementation requests for Codex."""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class CodexChangeRequest(Base):
    __tablename__ = "codex_change_requests"
    __table_args__ = (
        UniqueConstraint("change_request_id", name="uq_codex_change_requests_change_request_id"),
        UniqueConstraint("report_id", "proposal_id", name="uq_codex_change_requests_report_proposal"),
        CheckConstraint(
            "status IN ('proposed', 'approved', 'running', 'verified', 'implemented', 'deferred', 'failed')",
            name="ck_codex_change_requests_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    change_request_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("crawl_analysis_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    proposal_id: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="proposed", index=True)
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    target_files: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    change_scope: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    verification_plan: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    codex_run_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    commit_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    test_results: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
