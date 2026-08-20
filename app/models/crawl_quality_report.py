"""Immutable per-crawl-job quality reports used by weekly analysis."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class CrawlQualityReport(Base):
    """One normalized quality snapshot for one completed crawl job.

    The report intentionally stores summary and record references only.  Failure
    payloads and provider responses remain in their dedicated audit tables.
    """

    __tablename__ = "crawl_quality_reports"
    __table_args__ = (
        UniqueConstraint("crawl_job_id", name="uq_crawl_quality_reports_crawl_job_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    crawl_job_id: Mapped[int] = mapped_column(
        ForeignKey("crawl_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    report_schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    trade_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    job_status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    symbols_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    symbols_succeeded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    symbols_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    coverage_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error_distribution: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    repeated_failure_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    anomaly_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    sample_refs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    report_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
