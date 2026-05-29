from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class Symbol(Base):
    __tablename__ = "symbols"
    __table_args__ = (
        Index("ix_symbols_market_active", "market", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    market: Mapped[str] = mapped_column(String(20), index=True)
    sector: Mapped[str | None] = mapped_column(String(255), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    listed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    delisted_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
