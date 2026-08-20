"""PostgreSQL-backed repair 업무와 결과의 감사 모델."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


REQUEST_STATUSES = ("pending", "processing", "completed", "failed", "expired", "cancelled", "legacy_hold")
APPLICATION_STATUSES = ("not_applied", "applied", "conflict", "rejected")
ATTEMPT_STATUSES = ("processing", "completed", "failed")


class CrawlRepairRequest(Base):
    """Naver 실패 종목에 대해 Sam에게 전달할 하나의 읽기 업무."""

    __tablename__ = "crawl_repair_requests"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_crawl_repair_requests_dedupe_key"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'expired', 'cancelled', 'legacy_hold')",
            name="ck_crawl_repair_requests_status",
        ),
        CheckConstraint(
            "application_status IN ('not_applied', 'applied', 'conflict', 'rejected')",
            name="ck_crawl_repair_requests_application_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_crawl_repair_requests_attempt_count"),
        CheckConstraint("max_attempts > 0", name="ck_crawl_repair_requests_max_attempts"),
        Index(
            "ix_crawl_repair_requests_ready",
            "status",
            "next_attempt_at",
            "requested_at",
        ),
        Index(
            "ix_crawl_repair_requests_lease",
            "status",
            "lease_expires_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("crawl_jobs.id"), nullable=True, index=True
    )
    crawl_target_result_id: Mapped[int | None] = mapped_column(
        ForeignKey("crawl_target_results.id"), nullable=True, index=True
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    history_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    operation: Mapped[str] = mapped_column(String(40), nullable=False, default="daily_chart")
    error_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="kiwoom")
    adjusted_price: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    application_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="not_applied", index=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )
    claimed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    claim_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    claim_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    application_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class CrawlRepairAttempt(Base):
    """Sam 또는 재시도별 실행 결과를 보존하는 감사 행."""

    __tablename__ = "crawl_repair_attempts"
    __table_args__ = (
        UniqueConstraint("request_id", "attempt_no", name="uq_crawl_repair_attempt_request_no"),
        CheckConstraint(
            "status IN ('processing', 'completed', 'failed')",
            name="ck_crawl_repair_attempts_status",
        ),
        CheckConstraint("row_count >= 0", name="ck_crawl_repair_attempts_row_count"),
        Index("ix_crawl_repair_attempts_request_status", "request_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("crawl_repair_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    executor: Mapped[str] = mapped_column(String(50), nullable=False, default="sam")
    tool: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mode: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="processing")
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latest_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    result_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class CrawlRepairResult(Base):
    """Kiwoom이 반환한 정규화된 날짜별 OHLC 행."""

    __tablename__ = "crawl_repair_results"
    __table_args__ = (
        UniqueConstraint(
            "request_id",
            "attempt_id",
            "symbol",
            "trade_date",
            name="uq_crawl_repair_results_attempt_symbol_date",
        ),
        CheckConstraint("open > 0", name="ck_crawl_repair_results_open_positive"),
        CheckConstraint("high > 0", name="ck_crawl_repair_results_high_positive"),
        CheckConstraint("low > 0", name="ck_crawl_repair_results_low_positive"),
        CheckConstraint("close > 0", name="ck_crawl_repair_results_close_positive"),
        CheckConstraint("volume >= 0", name="ck_crawl_repair_results_volume_nonnegative"),
        CheckConstraint("high >= low", name="ck_crawl_repair_results_high_low"),
        CheckConstraint("high >= open AND high >= close", name="ck_crawl_repair_results_high_bound"),
        CheckConstraint("low <= open AND low <= close", name="ck_crawl_repair_results_low_bound"),
        CheckConstraint(
            "application_status IN ('not_applied', 'applied', 'conflict', 'rejected')",
            name="ck_crawl_repair_results_application_status",
        ),
        Index("ix_crawl_repair_results_request_date", "request_id", "trade_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("crawl_repair_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("crawl_repair_attempts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="kiwoom")
    adjusted_price: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    change_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    application_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="not_applied", index=True
    )
    application_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
