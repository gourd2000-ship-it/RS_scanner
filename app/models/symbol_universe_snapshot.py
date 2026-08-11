from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class SymbolUniverseSnapshot(Base):
    """심볼 universe 수집 단위와 완전성 검증 결과."""

    __tablename__ = "symbol_universe_snapshots"
    __table_args__ = (
        Index("ix_universe_snapshots_market_started", "market", "started_at"),
        Index("ix_universe_snapshots_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("crawl_jobs.id"), nullable=True, index=True)
    market: Mapped[str] = mapped_column(String(20), default="ALL")
    provider: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="running")
    pages_total: Mapped[int] = mapped_column(Integer, default=0)
    pages_succeeded: Mapped[int] = mapped_column(Integer, default=0)
    symbols_seen: Mapped[int] = mapped_column(Integer, default=0)
    symbols_valid: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, default=0)
    snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deactivation_candidates: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
