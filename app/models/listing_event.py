"""Immutable, source-backed revisions of historical listing events."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class ListingEvent(Base):
    """One evidence revision, never an inferred price-derived listing boundary."""

    __tablename__ = "listing_events"
    __table_args__ = (
        UniqueConstraint("source", "source_record_key", "content_hash", name="uq_listing_events_source_record_hash"),
        Index("ix_listing_events_instrument_effective", "instrument_id", "effective_from"),
        Index("ix_listing_events_source_record", "source", "source_record_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    source_contract_version: Mapped[str] = mapped_column(String(100), nullable=False)
    source_record_key: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(100), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_trading_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    market: Mapped[str | None] = mapped_column(String(20), nullable=True)
    market_to: Mapped[str | None] = mapped_column(String(20), nullable=True)
    provider_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider_code_to: Mapped[str | None] = mapped_column(String(50), nullable=True)
    trading_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_state: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("listing_events.id"), nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
