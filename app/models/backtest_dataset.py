"""Immutable materialized historical datasets for reproducible backtests."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base import Base


class BacktestDataset(Base):
    __tablename__ = "backtest_datasets"
    __table_args__ = (
        Index("ix_backtest_datasets_status_retention", "status", "retention_until"),
        Index("ix_backtest_datasets_range", "range_start", "range_end"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    manifest_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    final_manifest_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    range_start: Mapped[date] = mapped_column(Date)
    range_end: Mapped[date] = mapped_column(Date)
    markets: Mapped[list[str]] = mapped_column(JSON)
    reconstruction_mode: Mapped[str] = mapped_column(String(40))
    as_known_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    adjustment_policy: Mapped[str] = mapped_column(String(100))
    policy_version: Mapped[str] = mapped_column(String(100))
    preparation_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    manifest: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="active")
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    prices: Mapped[list["BacktestDatasetPrice"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", order_by="BacktestDatasetPrice.trade_date"
    )
    memberships: Mapped[list["BacktestDatasetMembership"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", order_by="BacktestDatasetMembership.trade_date"
    )
    rs_runs: Mapped[list["BacktestDatasetRsRun"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )


class BacktestDatasetPrice(Base):
    __tablename__ = "backtest_dataset_prices"
    __table_args__ = (
        UniqueConstraint("backtest_dataset_id", "source_symbol_id", "trade_date", name="uq_backtest_dataset_price_symbol_date"),
        Index("ix_backtest_dataset_prices_dataset_date", "backtest_dataset_id", "trade_date"),
        Index("ix_backtest_dataset_prices_dataset_instrument_date", "backtest_dataset_id", "instrument_id", "trade_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    backtest_dataset_id: Mapped[int] = mapped_column(ForeignKey("backtest_datasets.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(Integer, index=True)
    source_symbol_id: Mapped[int] = mapped_column(Integer, index=True)
    source_observation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(255))
    market: Mapped[str] = mapped_column(String(20), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    high: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    low: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    close: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    volume: Mapped[int] = mapped_column(BigInteger)
    change_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    provider: Mapped[str] = mapped_column(String(100))
    adjustment_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correction_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)

    dataset: Mapped[BacktestDataset] = relationship(back_populates="prices")


class BacktestDatasetMembership(Base):
    __tablename__ = "backtest_dataset_memberships"
    __table_args__ = (
        UniqueConstraint("backtest_dataset_id", "instrument_id", "trade_date", name="uq_backtest_dataset_membership_date"),
        Index("ix_backtest_dataset_memberships_dataset_date", "backtest_dataset_id", "trade_date"),
        Index("ix_backtest_dataset_memberships_dataset_date_instrument", "backtest_dataset_id", "trade_date", "instrument_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    backtest_dataset_id: Mapped[int] = mapped_column(ForeignKey("backtest_datasets.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(Integer, index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    market: Mapped[str] = mapped_column(String(20), index=True)
    security_type: Mapped[str] = mapped_column(String(20))
    membership_evidence_state: Mapped[str] = mapped_column(String(20))
    trading_status: Mapped[str] = mapped_column(String(40))
    price_expectation: Mapped[str] = mapped_column(String(40))
    event_revision_hashes: Mapped[list[str]] = mapped_column(JSON, default=list)
    code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quality_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    quality_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    quality_evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    dataset: Mapped[BacktestDataset] = relationship(back_populates="memberships")


class BacktestDatasetRsRun(Base):
    __tablename__ = "backtest_dataset_rs_runs"
    __table_args__ = (UniqueConstraint("backtest_dataset_id", "formula_version", name="uq_backtest_dataset_rs_run"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    backtest_dataset_id: Mapped[int] = mapped_column(ForeignKey("backtest_datasets.id"), index=True)
    formula_version: Mapped[str] = mapped_column(String(100))
    policy_version: Mapped[str] = mapped_column(String(100))
    input_hash: Mapped[str] = mapped_column(String(64))
    result_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="completed")
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    dataset: Mapped[BacktestDataset] = relationship(back_populates="rs_runs")
    rows: Mapped[list["BacktestDatasetRs"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class BacktestDatasetRs(Base):
    __tablename__ = "backtest_dataset_rs"
    __table_args__ = (
        UniqueConstraint("backtest_dataset_rs_run_id", "instrument_id", "trade_date", name="uq_backtest_dataset_rs_target"),
        Index("ix_backtest_dataset_rs_dataset_date", "backtest_dataset_id", "trade_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    backtest_dataset_rs_run_id: Mapped[int] = mapped_column(ForeignKey("backtest_dataset_rs_runs.id"), index=True)
    backtest_dataset_id: Mapped[int] = mapped_column(ForeignKey("backtest_datasets.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(Integer, index=True)
    code: Mapped[str] = mapped_column(String(20))
    market: Mapped[str] = mapped_column(String(20))
    trade_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))
    reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    required_observations: Mapped[int] = mapped_column(Integer)
    available_observations: Mapped[int] = mapped_column(Integer)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    return_1m: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    return_3m: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    return_6m: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    return_9m: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    return_12m: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    relative_return_score: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    rs_percentile: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    rs_1m: Mapped[int] = mapped_column(Integer, default=0)
    rs_3m: Mapped[int] = mapped_column(Integer, default=0)
    rs_6m: Mapped[int] = mapped_column(Integer, default=0)
    rs_12m: Mapped[int] = mapped_column(Integer, default=0)
    rs_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rank_in_market: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rank_in_universe: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_hash: Mapped[str] = mapped_column(String(64))

    run: Mapped[BacktestDatasetRsRun] = relationship(back_populates="rows")
