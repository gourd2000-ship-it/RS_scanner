"""Persistent BT06 historical-price backfill state.

The target manifest is intentionally stored with the run.  A continuation key
belongs to one provider response only; confirmed trade dates are the durable
resume boundary.
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base import Base


class HistoricalBackfillRun(Base):
    __tablename__ = "historical_backfill_runs"
    __table_args__ = (Index("ix_historical_backfill_runs_status", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    manifest_hash: Mapped[str] = mapped_column(String(64), index=True)
    manifest: Mapped[dict] = mapped_column(JSON)
    range_start: Mapped[date] = mapped_column(Date)
    range_end: Mapped[date] = mapped_column(Date)
    provider: Mapped[str] = mapped_column(String(100))
    adjustment_type: Mapped[str] = mapped_column(String(50))
    base_date: Mapped[str] = mapped_column(String(8))
    request_budget: Mapped[int] = mapped_column(Integer)
    requests_used: Mapped[int] = mapped_column(Integer, default=0)
    dry_run: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(30), default="running")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    targets: Mapped[list["HistoricalBackfillTargetState"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="HistoricalBackfillTargetState.id"
    )


class HistoricalBackfillTargetState(Base):
    __tablename__ = "historical_backfill_target_states"
    __table_args__ = (
        UniqueConstraint("historical_backfill_run_id", "instrument_id", "market", name="uq_backfill_target_run_instrument_market"),
        Index("ix_backfill_target_run_status", "historical_backfill_run_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    historical_backfill_run_id: Mapped[int] = mapped_column(
        ForeignKey("historical_backfill_runs.id"), index=True
    )
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    symbol_id: Mapped[int | None] = mapped_column(ForeignKey("symbols.id"), nullable=True, index=True)
    provider_code: Mapped[str] = mapped_column(String(50))
    market: Mapped[str] = mapped_column(String(20))
    expected_dates: Mapped[list[str]] = mapped_column(JSON, default=list)
    confirmed_dates: Mapped[list[str]] = mapped_column(JSON, default=list)
    remaining_dates: Mapped[list[str]] = mapped_column(JSON, default=list)
    confirmed_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    confirmed_through: Mapped[date | None] = mapped_column(Date, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    failure_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    run: Mapped[HistoricalBackfillRun] = relationship(back_populates="targets")
