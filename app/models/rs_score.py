from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class RsScore(Base):
    __tablename__ = "rs_scores"
    __table_args__ = (
        UniqueConstraint("symbol_id", "trade_date", name="uq_rs_scores_symbol_date"),
        Index("ix_rs_scores_trade_date_market_rating", "trade_date", "market", "rs_rating"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id"), index=True)
    benchmark_id: Mapped[int] = mapped_column(ForeignKey("benchmarks.id"), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    market: Mapped[str] = mapped_column(String(20), index=True)
    return_3m: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    return_6m: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    return_9m: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    return_12m: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    relative_return_score: Mapped[Decimal] = mapped_column(Numeric(12, 6), index=True)
    rs_percentile: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    rs_rating: Mapped[int] = mapped_column(Integer, index=True)
    rank_in_market: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
