"""Canonical KRX instrument identity and provider mapping models."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint("krx_short_code", name="uq_instruments_krx_short_code"),
        UniqueConstraint("isin", name="uq_instruments_isin"),
        Index("ix_instruments_market_type_status", "market", "security_type", "listing_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    krx_short_code: Mapped[str] = mapped_column(String(20), nullable=False)
    isin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    market: Mapped[str] = mapped_column(String(20), nullable=False)
    security_type: Mapped[str] = mapped_column(String(20), nullable=False)
    listed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    delisted_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    listing_status: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ProviderSymbol(Base):
    __tablename__ = "provider_symbols"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "provider", "provider_symbol", "valid_from",
            name="uq_provider_symbols_version",
        ),
        Index("ix_provider_symbols_provider_status", "provider", "mapping_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    mapping_status: Mapped[str] = mapped_column(String(30), nullable=False)
    evidence_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("krx_universe_snapshots.id"), nullable=True
    )
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class UniverseExclusion(Base):
    __tablename__ = "universe_exclusions"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "scope", "reason_code", "valid_from",
            name="uq_universe_exclusions_version",
        ),
        Index("ix_universe_exclusions_scope_active", "scope", "valid_to"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    scope: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    evidence_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("krx_universe_snapshots.id"), nullable=True
    )
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
