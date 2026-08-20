"""승인 기반 legacy universe 정리의 감사 모델."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class UniverseAuditRun(Base):
    __tablename__ = "universe_audit_runs"
    __table_args__ = (
        Index("ix_universe_audit_runs_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("symbol_universe_snapshots.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    applied_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    report: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class UniverseAuditDecision(Base):
    __tablename__ = "universe_audit_decisions"
    __table_args__ = (
        UniqueConstraint("run_id", "symbol_id", name="uq_universe_audit_decision_run_symbol"),
        Index("ix_universe_audit_decisions_run_status", "run_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("universe_audit_runs.id"), nullable=False, index=True
    )
    symbol_id: Mapped[int | None] = mapped_column(
        ForeignKey("symbols.id"), nullable=True, index=True
    )
    original_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    replacement_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    action: Mapped[str] = mapped_column(String(30), default="deactivate")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
