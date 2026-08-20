"""Models for user-requested weekly crawl-quality analysis."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class CrawlAnalysisRequest(Base):
    __tablename__ = "crawl_analysis_requests"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_crawl_analysis_requests_request_id"),
        UniqueConstraint("idempotency_key", name="uq_crawl_analysis_requests_idempotency_key"),
        CheckConstraint("request_kind IN ('weekly', 'ad_hoc')", name="ck_crawl_analysis_requests_kind"),
        CheckConstraint(
            "status IN ('requested', 'accepted', 'report_ready', 'codex_reviewed', "
            "'implemented', 'partially_implemented', 'deferred')",
            name="ck_crawl_analysis_requests_status",
        ),
        CheckConstraint(
            "sample_limit >= 1 AND sample_limit <= 10",
            name="ck_crawl_analysis_requests_sample_limit",
        ),
        CheckConstraint("period_from <= period_to", name="ck_crawl_analysis_requests_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    request_kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="requested", index=True)
    period_from: Mapped[date] = mapped_column(Date, nullable=False)
    period_to: Mapped[date] = mapped_column(Date, nullable=False)
    completed_job_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    error_types: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    markets: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    sample_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    accepted_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class CrawlAnalysisRequestQualityReport(Base):
    __tablename__ = "crawl_analysis_request_quality_reports"
    __table_args__ = (
        UniqueConstraint(
            "analysis_request_id",
            "quality_report_id",
            name="uq_analysis_request_quality_report",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_request_id: Mapped[int] = mapped_column(
        ForeignKey("crawl_analysis_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quality_report_id: Mapped[int] = mapped_column(
        ForeignKey("crawl_quality_reports.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class CrawlAnalysisReport(Base):
    __tablename__ = "crawl_analysis_reports"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_crawl_analysis_reports_request_id"),
        UniqueConstraint("report_hash", name="uq_crawl_analysis_reports_report_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("crawl_analysis_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[str] = mapped_column(String(100), nullable=False, default="sam")
    analysis_window: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    quality_report_refs: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    kiwoom_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    recommendations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    limitations: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    markdown_body: Mapped[str] = mapped_column(Text, nullable=False)
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    report_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
