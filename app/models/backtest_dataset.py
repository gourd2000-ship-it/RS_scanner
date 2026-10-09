"""Immutable materialized historical datasets for reproducible backtests."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    UniqueConstraint,
)
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


class BacktestDatasetIndicatorSnapshot(Base):
    """A completed, immutable bundle of indicator values pinned to one dataset."""

    __tablename__ = "backtest_dataset_indicator_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_key", name="uq_backtest_indicator_snapshot_key"),
        CheckConstraint("indicator_kind IN ('volume_sma', 'atr')", name="ck_backtest_indicator_snapshot_kind"),
        CheckConstraint(
            "(indicator_kind = 'volume_sma' AND period = 50 AND formula_version = 'volume-sma-v1') OR "
            "(indicator_kind = 'atr' AND period = 14 AND formula_version = 'wilder-atr-14-v1')",
            name="ck_backtest_indicator_snapshot_definition",
        ),
        CheckConstraint("range_start <= range_end", name="ck_backtest_indicator_snapshot_range"),
        CheckConstraint("status IN ('building', 'complete')", name="ck_backtest_indicator_snapshot_status"),
        CheckConstraint("source_count > 0 AND row_count > 0", name="ck_backtest_indicator_snapshot_counts"),
        CheckConstraint("status = 'building' OR completed_at IS NOT NULL", name="ck_backtest_indicator_snapshot_completed_at"),
        CheckConstraint(
            "length(source_policy_fingerprint) = 64 AND length(input_hash) = 64 "
            "AND length(result_hash) = 64 AND length(content_hash) = 64",
            name="ck_backtest_indicator_snapshot_hashes",
        ),
        Index("ix_backtest_indicator_snapshot_dataset", "backtest_dataset_id", "indicator_kind", "period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_key: Mapped[str] = mapped_column(String(64), nullable=False)
    backtest_dataset_id: Mapped[int] = mapped_column(ForeignKey("backtest_datasets.id"), nullable=False)
    dataset_id: Mapped[str] = mapped_column(String(80), nullable=False)
    dataset_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    indicator_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    period: Mapped[int] = mapped_column(Integer, nullable=False)
    formula_version: Mapped[str] = mapped_column(String(100), nullable=False)
    source_policy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    range_start: Mapped[date] = mapped_column(Date, nullable=False)
    range_end: Mapped[date] = mapped_column(Date, nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="building")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BacktestDatasetIndicatorSnapshotSource(Base):
    """The exact indicator series, generation, run and policy for one instrument."""

    __tablename__ = "backtest_dataset_indicator_snapshot_sources"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "instrument_id", name="uq_backtest_indicator_snapshot_source_instrument"),
        UniqueConstraint("id", "snapshot_id", "instrument_id", name="uq_backtest_indicator_snapshot_source_identity"),
        ForeignKeyConstraint(
            ["generation_id", "indicator_series_id"],
            ["indicator_generations.id", "indicator_generations.series_id"],
            name="fk_backtest_indicator_snapshot_source_generation_series",
        ),
        ForeignKeyConstraint(
            ["calculation_run_id", "generation_id"],
            ["indicator_calculation_runs.id", "indicator_calculation_runs.generation_id"],
            name="fk_backtest_indicator_snapshot_source_run_generation",
        ),
        CheckConstraint(
            "length(source_policy_fingerprint) = 64 AND length(input_hash) = 64 AND length(result_hash) = 64",
            name="ck_backtest_indicator_snapshot_source_hashes",
        ),
        Index("ix_backtest_indicator_snapshot_source_run", "calculation_run_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("backtest_dataset_indicator_snapshots.id"), nullable=False)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    indicator_series_id: Mapped[int] = mapped_column(ForeignKey("indicator_series.id"), nullable=False)
    generation_id: Mapped[int] = mapped_column(Integer, nullable=False)
    calculation_run_id: Mapped[int] = mapped_column(Integer, nullable=False)
    input_policy_id: Mapped[int] = mapped_column(ForeignKey("indicator_input_policies.id"), nullable=False)
    source_policy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class BacktestDatasetIndicatorSnapshotRow(Base):
    """One dataset-day value and its copied identity/source/OHLCV evidence."""

    __tablename__ = "backtest_dataset_indicator_snapshot_rows"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "instrument_id", "trade_date", name="uq_backtest_indicator_snapshot_value_date"),
        ForeignKeyConstraint(
            ["source_id", "snapshot_id", "instrument_id"],
            ["backtest_dataset_indicator_snapshot_sources.id",
             "backtest_dataset_indicator_snapshot_sources.snapshot_id",
             "backtest_dataset_indicator_snapshot_sources.instrument_id"],
            name="fk_backtest_indicator_snapshot_row_source",
        ),
        CheckConstraint("status IN ('available', 'warming_up', 'data_unavailable')", name="ck_backtest_indicator_snapshot_row_status"),
        CheckConstraint(
            "(status = 'available' AND value IS NOT NULL AND reason_code IS NULL) OR "
            "(status = 'warming_up' AND value IS NULL AND reason_code = 'warming_up') OR "
            "(status = 'data_unavailable' AND value IS NULL AND reason_code IS NOT NULL AND reason_code <> 'warming_up')",
            name="ck_backtest_indicator_snapshot_row_value_shape",
        ),
        CheckConstraint("available_observations >= 0", name="ck_backtest_indicator_snapshot_row_observation_count"),
        CheckConstraint("mapping_status = 'matched'", name="ck_backtest_indicator_snapshot_row_matched_identity"),
        CheckConstraint(
            "mapping_valid_to IS NULL OR mapping_valid_from IS NULL OR mapping_valid_from < mapping_valid_to",
            name="ck_backtest_indicator_snapshot_row_mapping_range",
        ),
        CheckConstraint(
            "open > 0 AND high > 0 AND low > 0 AND close > 0 AND volume >= 0 "
            "AND high >= low AND high >= open AND high >= close AND low <= open AND low <= close",
            name="ck_backtest_indicator_snapshot_row_valid_ohlcv",
        ),
        CheckConstraint(
            "length(input_prefix_hash) = 64 AND length(source_evidence_key) = 64 AND length(row_hash) = 64",
            name="ck_backtest_indicator_snapshot_row_hashes",
        ),
        Index("ix_backtest_indicator_snapshot_row_lookup", "snapshot_id", "trade_date", "instrument_id"),
        Index("ix_backtest_indicator_snapshot_row_source_value", "source_value_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("backtest_dataset_indicator_snapshots.id"), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_value_id: Mapped[int] = mapped_column(ForeignKey("indicator_values.id"), nullable=False)
    source_run_input_id: Mapped[int] = mapped_column(ForeignKey("indicator_run_inputs.id"), nullable=False)
    source_evidence_id: Mapped[int] = mapped_column(ForeignKey("indicator_input_evidence.id"), nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    available_observations: Mapped[int] = mapped_column(Integer, nullable=False)
    input_prefix_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_evidence_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id"), nullable=False)
    price_observation_id: Mapped[int] = mapped_column(ForeignKey("price_observations.id"), nullable=False)
    identity_snapshot_id: Mapped[int] = mapped_column(ForeignKey("price_observation_identity_snapshots.id"), nullable=False)
    provider_symbol_mapping_id: Mapped[int] = mapped_column(ForeignKey("provider_symbols.id"), nullable=False)
    mapping_status: Mapped[str] = mapped_column(String(30), nullable=False)
    mapping_valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    mapping_valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    resolver_version: Mapped[str] = mapped_column(String(100), nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    adjustment_type: Mapped[str] = mapped_column(String(100), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(100), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    correction_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    validation_evidence: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)
