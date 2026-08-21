"""Operator decisions recorded for each KRX canary trading day."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class UniverseCanaryDecision(Base):
    """Immutable operator decision backed by the batch's observed evidence."""

    __tablename__ = "universe_canary_decisions"
    __table_args__ = (
        UniqueConstraint("trade_date", "market", name="uq_universe_canary_decision_date_market"),
        Index("ix_universe_canary_decisions_job", "crawl_job_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    crawl_job_id: Mapped[int] = mapped_column(ForeignKey("crawl_jobs.id"), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    market: Mapped[str] = mapped_column(String(20), nullable=False)
    krx_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("krx_universe_snapshots.id"), nullable=True
    )
    reconciliation_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("universe_reconciliation_runs.id"), nullable=True
    )
    selected_reconciliation_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("universe_reconciliation_runs.id"), nullable=True
    )
    authority: Mapped[str] = mapped_column(String(40), nullable=False)
    fallback_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mapping_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_count: Mapped[int] = mapped_column(Integer, nullable=False)
    operator_decision: Mapped[str] = mapped_column(String(20), nullable=False)
    approved_by: Mapped[str] = mapped_column(String(100), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
