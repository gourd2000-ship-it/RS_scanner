"""Auditable reconciliation runs for KRX and Naver universe snapshots."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class UniverseReconciliationRun(Base):
    __tablename__ = "universe_reconciliation_runs"
    __table_args__ = (
        UniqueConstraint(
            "krx_snapshot_id", "naver_snapshot_id",
            name="uq_universe_reconciliation_snapshot_pair",
        ),
        Index("ix_universe_reconciliation_runs_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    krx_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("krx_universe_snapshots.id"), nullable=False
    )
    naver_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("symbol_universe_snapshots.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending_review")
    report: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    decision: Mapped[str | None] = mapped_column(String(30), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
