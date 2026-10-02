"""Immutable inputs and persisted outputs for domestic-stock backtests.

The tables in this module deliberately hold a copy of every input that could
otherwise change after a run is queued: a strategy version, final dataset
manifest, RS result and both benchmark close series.  They model a simulation;
they never represent a brokerage order or account.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base import Base


BACKTEST_RUN_STATUSES = frozenset({
    "queued", "running", "cancelled", "failed", "data_unavailable", "completed",
})
BACKTEST_TERMINAL_STATUSES = frozenset({"cancelled", "failed", "data_unavailable", "completed"})


class BacktestStrategy(Base):
    __tablename__ = "backtest_strategies"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    versions: Mapped[list["BacktestStrategyVersion"]] = relationship(
        back_populates="strategy", cascade="all, delete-orphan", order_by="BacktestStrategyVersion.version"
    )


class BacktestStrategyVersion(Base):
    __tablename__ = "backtest_strategy_versions"
    __table_args__ = (
        UniqueConstraint("backtest_strategy_id", "version", name="uq_backtest_strategy_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    backtest_strategy_id: Mapped[int] = mapped_column(
        ForeignKey("backtest_strategies.id"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict] = mapped_column(JSON)
    config_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    strategy: Mapped[BacktestStrategy] = relationship(back_populates="versions")
    runs: Mapped[list["BacktestRun"]] = relationship(back_populates="strategy_version")


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'cancelled', 'failed', 'data_unavailable', 'completed')",
            name="ck_backtest_runs_status",
        ),
        Index("ix_backtest_runs_queue", "status", "queued_at", "id"),
        Index("ix_backtest_runs_strategy_version", "backtest_strategy_version_id"),
        Index("ix_backtest_runs_dataset", "backtest_dataset_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    backtest_strategy_version_id: Mapped[int] = mapped_column(
        ForeignKey("backtest_strategy_versions.id"), index=True
    )
    backtest_dataset_id: Mapped[int] = mapped_column(
        ForeignKey("backtest_datasets.id"), index=True
    )
    backtest_dataset_rs_run_id: Mapped[int] = mapped_column(
        ForeignKey("backtest_dataset_rs_runs.id"), index=True
    )
    dataset_id: Mapped[str] = mapped_column(String(80), index=True)
    dataset_manifest_hash: Mapped[str] = mapped_column(String(64), index=True)
    rs_result_hash: Mapped[str] = mapped_column(String(64), index=True)
    range_start: Mapped[date] = mapped_column(Date)
    range_end: Mapped[date] = mapped_column(Date)
    markets: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    strategy_version: Mapped[BacktestStrategyVersion] = relationship(back_populates="runs")
    benchmark_snapshots: Mapped[list["BacktestBenchmarkSnapshot"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="BacktestBenchmarkSnapshot.market"
    )
    daily_equity: Mapped[list["BacktestDailyEquity"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="BacktestDailyEquity.trade_date"
    )
    orders: Mapped[list["BacktestOrder"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="BacktestOrder.sequence"
    )
    trades: Mapped[list["BacktestTrade"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="BacktestTrade.id"
    )


class BacktestBenchmarkSnapshot(Base):
    __tablename__ = "backtest_benchmark_snapshots"
    __table_args__ = (
        UniqueConstraint("backtest_run_id", "market", name="uq_backtest_benchmark_snapshot_run_market"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    backtest_run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"), index=True)
    market: Mapped[str] = mapped_column(String(20))
    benchmark_code: Mapped[str] = mapped_column(String(50))
    snapshot_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    run: Mapped[BacktestRun] = relationship(back_populates="benchmark_snapshots")
    prices: Mapped[list["BacktestBenchmarkSnapshotPrice"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan", order_by="BacktestBenchmarkSnapshotPrice.trade_date"
    )


class BacktestBenchmarkSnapshotPrice(Base):
    __tablename__ = "backtest_benchmark_snapshot_prices"
    __table_args__ = (
        UniqueConstraint("backtest_benchmark_snapshot_id", "trade_date", name="uq_backtest_benchmark_snapshot_price"),
        Index("ix_backtest_benchmark_snapshot_prices_date", "backtest_benchmark_snapshot_id", "trade_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    backtest_benchmark_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("backtest_benchmark_snapshots.id"), index=True
    )
    trade_date: Mapped[date] = mapped_column(Date)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 4))

    snapshot: Mapped[BacktestBenchmarkSnapshot] = relationship(back_populates="prices")


class BacktestDailyEquity(Base):
    __tablename__ = "backtest_daily_equity"
    __table_args__ = (
        UniqueConstraint("backtest_run_id", "trade_date", name="uq_backtest_daily_equity_run_date"),
        Index("ix_backtest_daily_equity_run_date", "backtest_run_id", "trade_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    backtest_run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"), index=True)
    trade_date: Mapped[date] = mapped_column(Date)
    cash: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    holdings_value: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    net_asset_value: Mapped[Decimal] = mapped_column(Numeric(18, 2))

    run: Mapped[BacktestRun] = relationship(back_populates="daily_equity")


class BacktestOrder(Base):
    __tablename__ = "backtest_orders"
    __table_args__ = (
        UniqueConstraint("backtest_run_id", "sequence", name="uq_backtest_order_run_sequence"),
        Index("ix_backtest_orders_run_execution", "backtest_run_id", "execution_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    backtest_run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    instrument_id: Mapped[int] = mapped_column(Integer, index=True)
    code: Mapped[str] = mapped_column(String(20))
    side: Mapped[str] = mapped_column(String(4))
    signal_date: Mapped[date] = mapped_column(Date)
    execution_date: Mapped[date] = mapped_column(Date)
    quantity: Mapped[int] = mapped_column(Integer)
    execution_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    fee: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    slippage: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="filled")

    run: Mapped[BacktestRun] = relationship(back_populates="orders")


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"
    __table_args__ = (Index("ix_backtest_trades_run_exit", "backtest_run_id", "exit_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    backtest_run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(Integer, index=True)
    code: Mapped[str] = mapped_column(String(20))
    entry_date: Mapped[date] = mapped_column(Date)
    exit_date: Mapped[date] = mapped_column(Date)
    quantity: Mapped[int] = mapped_column(Integer)
    entry_value: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    exit_value: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    profit_loss: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    return_rate: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    exit_reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list)

    run: Mapped[BacktestRun] = relationship(back_populates="trades")


class BacktestOperatorSession(Base):
    __tablename__ = "backtest_operator_sessions"
    __table_args__ = (Index("ix_backtest_operator_sessions_expiry", "expires_at", "revoked_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    operator_subject_hash: Mapped[str] = mapped_column(String(64), index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BacktestOperatorLoginAttempt(Base):
    __tablename__ = "backtest_operator_login_attempts"
    __table_args__ = (Index("ix_backtest_operator_login_attempts_subject_time", "subject_hash", "attempted_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_hash: Mapped[str] = mapped_column(String(64), index=True)
    succeeded: Mapped[bool] = mapped_column(default=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class BacktestOperatorLockout(Base):
    __tablename__ = "backtest_operator_lockouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    locked_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
