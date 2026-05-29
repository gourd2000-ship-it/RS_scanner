from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class DailyPrice(Base):
    __tablename__ = "daily_prices"
    __table_args__ = (
        UniqueConstraint("symbol_id", "trade_date", name="uq_daily_prices_symbol_date"),
        Index("ix_daily_prices_symbol_trade_date", "symbol_id", "trade_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id"), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    high: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    low: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    close: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    volume: Mapped[int] = mapped_column()
    change_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    source: Mapped[str] = mapped_column(String(50), default="naver")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
