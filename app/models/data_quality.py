"""Data-quality audit, observation and RS lineage models.

The existing ``daily_prices`` tables remain the canonical read/write tables for
backward compatibility.  These models add the audit trail around them without
letting a validator or an agent mutate the canonical rows in-place.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class ValidationRun(Base):
    """One deterministic validation evaluation for a crawl job or replay."""

    __tablename__ = "validation_runs"
    __table_args__ = (
        Index("ix_validation_runs_job_trade_date", "crawl_job_id", "trade_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    crawl_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("crawl_jobs.id"), nullable=True, index=True
    )
    trade_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    run_kind: Mapped[str] = mapped_column(String(30), default="daily")
    validator_version: Mapped[str] = mapped_column(String(50))
    mode: Mapped[str] = mapped_column(String(20), default="report_only")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expected_symbols: Mapped[int] = mapped_column(Integer, default=0)
    fresh_symbols: Mapped[int] = mapped_column(Integer, default=0)
    stale_symbols: Mapped[int] = mapped_column(Integer, default=0)
    rs_candidate_symbols: Mapped[int] = mapped_column(Integer, default=0)
    pass_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    critical_count: Mapped[int] = mapped_column(Integer, default=0)
    coverage_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=Decimal("0"))
    rs_fresh_input_coverage_rate: Mapped[Decimal] = mapped_column(
        Numeric(8, 6), default=Decimal("0")
    )
    validation_status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ValidationCase(Base):
    """An anomaly or policy finding emitted by a validation run."""

    __tablename__ = "validation_cases"
    __table_args__ = (
        Index("ix_validation_cases_run_severity", "validation_run_id", "severity"),
        Index("ix_validation_cases_subject", "subject_type", "symbol_id", "trade_date"),
        Index("ix_validation_cases_rule_reason", "rule_id", "reason_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    validation_run_id: Mapped[int] = mapped_column(
        ForeignKey("validation_runs.id"), index=True
    )
    subject_type: Mapped[str] = mapped_column(String(30))
    symbol_id: Mapped[int | None] = mapped_column(
        ForeignKey("symbols.id"), nullable=True, index=True
    )
    benchmark_id: Mapped[int | None] = mapped_column(
        ForeignKey("benchmarks.id"), nullable=True, index=True
    )
    target_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    trade_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    rule_id: Mapped[str] = mapped_column(String(80), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    reason_code: Mapped[str] = mapped_column(String(80), index=True)
    case_status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    validator_version: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PriceObservation(Base):
    """Append-only normalized observation for a stock price response."""

    __tablename__ = "price_observations"
    __table_args__ = (
        Index("ix_price_observations_symbol_date", "symbol_id", "trade_date"),
        Index("ix_price_observations_job", "crawl_job_id"),
        Index("ix_price_observations_hash", "payload_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id"), index=True)
    crawl_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("crawl_jobs.id"), nullable=True, index=True
    )
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    high: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    low: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    close: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    volume: Mapped[int] = mapped_column(BigInteger)
    change_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    provider: Mapped[str] = mapped_column(String(100), default="naver")
    parser_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    observation_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BenchmarkObservation(Base):
    """Append-only normalized observation for a benchmark response."""

    __tablename__ = "benchmark_observations"
    __table_args__ = (
        Index("ix_benchmark_observations_benchmark_date", "benchmark_id", "trade_date"),
        Index("ix_benchmark_observations_job", "crawl_job_id"),
        Index("ix_benchmark_observations_hash", "payload_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    benchmark_id: Mapped[int] = mapped_column(ForeignKey("benchmarks.id"), index=True)
    crawl_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("crawl_jobs.id"), nullable=True, index=True
    )
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    high: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    low: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    close: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    change_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    provider: Mapped[str] = mapped_column(String(100), default="naver")
    parser_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    observation_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OhlcCorrection(Base):
    """Proposed or approved field correction; never mutates canonical prices."""

    __tablename__ = "ohlc_corrections"
    __table_args__ = (
        Index("ix_ohlc_corrections_symbol_date", "symbol_id", "trade_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id"), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    field_name: Mapped[str] = mapped_column(String(30))
    original_value: Mapped[object | None] = mapped_column(JSON, nullable=True)
    corrected_value: Mapped[object | None] = mapped_column(JSON, nullable=True)
    reason_code: Mapped[str] = mapped_column(String(80))
    reference_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reference_value: Mapped[object | None] = mapped_column(JSON, nullable=True)
    validation_case_id: Mapped[int | None] = mapped_column(
        ForeignKey("validation_cases.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="PROPOSED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OhlcExclusion(Base):
    """Explicit policy excluding a canonical row from validated reads."""

    __tablename__ = "ohlc_exclusions"
    __table_args__ = (
        UniqueConstraint("symbol_id", "trade_date", name="uq_ohlc_exclusions_symbol_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id"), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    reason_code: Mapped[str] = mapped_column(String(80))
    validation_case_id: Mapped[int | None] = mapped_column(
        ForeignKey("validation_cases.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="PROPOSED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CorporateAction(Base):
    """Corporate-action evidence used to explain extreme returns."""

    __tablename__ = "corporate_actions"
    __table_args__ = (
        Index("ix_corporate_actions_symbol_date", "symbol_id", "event_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id"), index=True)
    event_date: Mapped[date] = mapped_column(Date, index=True)
    event_type: Mapped[str] = mapped_column(String(50))
    ratio: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(100), default="deterministic")
    validation_case_id: Mapped[int | None] = mapped_column(
        ForeignKey("validation_cases.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RsRun(Base):
    """Metadata for one RS calculation and its validation dependency."""

    __tablename__ = "rs_runs"
    __table_args__ = (Index("ix_rs_runs_trade_status", "trade_date", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    validation_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("validation_runs.id"), nullable=True, index=True
    )
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    input_policy_version: Mapped[str] = mapped_column(String(50), default="v1")
    mode: Mapped[str] = mapped_column(String(20), default="legacy")
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    symbol_count: Mapped[int] = mapped_column(Integer, default=0)
    snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RsInputSnapshot(Base):
    """Per-symbol input lineage captured for an RS run."""

    __tablename__ = "rs_input_snapshots"
    __table_args__ = (
        UniqueConstraint("rs_run_id", "symbol_id", name="uq_rs_input_snapshot_run_symbol"),
        Index("ix_rs_input_snapshot_target_date", "target_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rs_run_id: Mapped[int] = mapped_column(ForeignKey("rs_runs.id"), index=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id"), index=True)
    target_date: Mapped[date] = mapped_column(Date)
    input_trade_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    stale_lag_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_status: Mapped[str] = mapped_column(String(30))
    price_row_count: Mapped[int] = mapped_column(Integer, default=0)
    price_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
