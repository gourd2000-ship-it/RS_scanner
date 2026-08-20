"""KRX 기준일 유니버스 원본 snapshot과 membership 모델."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class KrxUniverseSnapshot(Base):
    """KRX API의 기준일별 수집 결과를 재현 가능하게 보관한다."""

    __tablename__ = "krx_universe_snapshots"
    __table_args__ = (
        Index(
            "ix_krx_universe_snapshots_scope_status_as_of",
            "scope",
            "status",
            "as_of_date",
        ),
        Index("ix_krx_universe_snapshots_job_id", "crawl_job_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    crawl_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("crawl_jobs.id"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    scope: Mapped[str] = mapped_column(String(50), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    members_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    members_valid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class KrxUniverseMembership(Base):
    """하나의 KRX snapshot에 관측된 종목 membership 원문 정규화 행."""

    __tablename__ = "krx_universe_memberships"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "code", name="uq_krx_universe_membership_snapshot_code"),
        Index("ix_krx_universe_memberships_snapshot_market", "snapshot_id", "market"),
        Index("ix_krx_universe_memberships_code", "code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("krx_universe_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    isin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    market: Mapped[str] = mapped_column(String(20), nullable=False)
    security_type: Mapped[str] = mapped_column(String(20), nullable=False)
    listing_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="listed_observed"
    )
    trading_status: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    listed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    raw_fields: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
