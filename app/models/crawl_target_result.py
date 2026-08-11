from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class CrawlTargetResult(Base):
    """종목·단계별 마지막 시도 결과와 관측 메타데이터."""

    __tablename__ = "crawl_target_results"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "step_name",
            "target_key",
            name="uq_crawl_target_result_job_step_target",
        ),
        Index("ix_crawl_target_results_job_step", "job_id", "step_name"),
        Index("ix_crawl_target_results_job_status", "job_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("crawl_jobs.id"), index=True)
    step_name: Mapped[str] = mapped_column(String(50), index=True)
    target_type: Mapped[str] = mapped_column(String(50), default="stock")
    target_key: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    rows_received: Mapped[int] = mapped_column(Integer, default=0)
    rows_persisted: Mapped[int] = mapped_column(Integer, default=0)
    latest_date_before: Mapped[date | None] = mapped_column(Date, nullable=True)
    latest_date_after: Mapped[date | None] = mapped_column(Date, nullable=True)
    trade_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_class: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
