"""Append-only persistence models for reproducible indicator calculations.

The calculation service works only from the immutable objects in
``app.services.indicators.contracts``.  These tables persist those objects and
the resulting values without treating a current ``Symbol`` or ``DailyPrice``
row as historical identity evidence.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    FetchedValue,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base
from app.services.indicators.contracts import (
    EMA_FORMULA_VERSION,
    EMA_PERIODS,
    INPUT_POLICY_VERSION,
    EmaInputStatus,
    EmaStatus,
    InputReasonCode,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


_EMA_PERIOD_SQL = ", ".join(str(period) for period in EMA_PERIODS)
_EMA_STATUS_SQL = ", ".join(f"'{status.value}'" for status in EmaStatus)
_INPUT_STATUS_SQL = ", ".join(f"'{status.value}'" for status in EmaInputStatus)
_REASON_CODE_SQL = ", ".join(f"'{reason.value}'" for reason in InputReasonCode)
_MAPPING_STATUS_SQL = ", ".join(
    f"'{status}'" for status in ("matched", "unmatched", "ambiguous", "invalid_legacy")
)
_JSON_POLICY = JSON().with_variant(JSONB, "postgresql")


class PriceObservationIdentitySnapshot(Base):
    """Immutable identity evidence resolved when a price was observed.

    ``instrument_id`` and ``provider_symbol_mapping_id`` intentionally remain
    nullable: an unavailable or ambiguous identity is evidence in its own
    right.  A later mapping must never be guessed into this snapshot.
    """

    __tablename__ = "price_observation_identity_snapshots"
    __table_args__ = (
        UniqueConstraint("price_observation_id", name="uq_price_observation_identity_snapshot_observation"),
        # Lets input snapshots prove that their copied identity row belongs to
        # the selected observation, not merely to an arbitrary snapshot ID.
        UniqueConstraint("id", "price_observation_id", name="uq_price_observation_identity_snapshot_id_observation"),
        CheckConstraint(
            f"mapping_status IS NULL OR mapping_status IN ({_MAPPING_STATUS_SQL})",
            name="ck_price_observation_identity_snapshot_mapping_status",
        ),
        CheckConstraint(
            "mapping_valid_to IS NULL OR mapping_valid_from IS NULL "
            "OR mapping_valid_from < mapping_valid_to",
            name="ck_price_observation_identity_snapshot_mapping_range",
        ),
        Index("ix_price_observation_identity_snapshot_instrument", "instrument_id"),
        Index("ix_price_observation_identity_snapshot_mapping", "provider_symbol_mapping_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    price_observation_id: Mapped[int] = mapped_column(
        ForeignKey("price_observations.id"), nullable=False
    )
    instrument_id: Mapped[int | None] = mapped_column(
        ForeignKey("instruments.id"), nullable=True
    )
    provider_symbol_mapping_id: Mapped[int | None] = mapped_column(
        ForeignKey("provider_symbols.id"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_symbol: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mapping_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    mapping_valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    mapping_valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    resolver_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class IndicatorSeries(Base):
    """One historical instrument, approved indicator definition and source policy."""

    __tablename__ = "indicator_series"
    __table_args__ = (
        Index(
            "uq_indicator_series_policy",
            "instrument_id",
            "indicator_kind",
            "input_field",
            "periods",
            "input_policy_version",
            "formula_version",
            "source_provider",
            "adjustment_policy",
            "allowed_parser_versions",
            "observation_cutoff",
            unique=True,
            postgresql_where=text("input_policy_id IS NULL"),
            sqlite_where=text("input_policy_id IS NULL"),
        ),
        UniqueConstraint("instrument_id", "indicator_kind", "input_policy_id", name="uq_indicator_series_common_policy"),
        CheckConstraint(
            "(indicator_kind = 'ema' AND input_field = 'close' AND periods = '5,20,50,200' "
            "AND formula_version = 'ema-close-seed-v1' AND "
            "((input_policy_version = 'validated-observation-close-v3' AND input_policy_id IS NULL) OR "
            "(input_policy_version = 'validated-observation-ohlcv-v1' AND input_policy_id IS NOT NULL))) OR "
            "(indicator_kind = 'volume_sma' AND input_field = 'volume' AND periods = '50' "
            "AND formula_version = 'volume-sma-v1' AND input_policy_version = 'validated-observation-ohlcv-v1' "
            "AND input_policy_id IS NOT NULL)",
            name="ck_indicator_series_definition",
        ),
        Index("ix_indicator_series_instrument", "instrument_id"),
        Index("ix_indicator_series_instrument_policy", "instrument_id", "input_policy_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    indicator_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="ema")
    input_field: Mapped[str] = mapped_column(String(20), nullable=False, default="close")
    periods: Mapped[str] = mapped_column(String(30), nullable=False, default=",".join(map(str, EMA_PERIODS)))
    input_policy_version: Mapped[str] = mapped_column(String(100), nullable=False, default=INPUT_POLICY_VERSION)
    formula_version: Mapped[str] = mapped_column(String(100), nullable=False, default=EMA_FORMULA_VERSION)
    source_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    adjustment_policy: Mapped[str] = mapped_column(String(100), nullable=False)
    allowed_parser_versions: Mapped[list[str]] = mapped_column(_JSON_POLICY, nullable=False)
    observation_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_policy_id: Mapped[int | None] = mapped_column(ForeignKey("indicator_input_policies.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class IndicatorGeneration(Base):
    """A logical replacement lineage below a policy series."""

    __tablename__ = "indicator_generations"
    __table_args__ = (
        UniqueConstraint("series_id", "generation", name="uq_indicator_generation_number"),
        ForeignKeyConstraint(
            ["parent_generation_id", "series_id"],
            ["indicator_generations.id", "indicator_generations.series_id"],
            name="fk_indicator_generation_parent_series",
        ),
        # This candidate key lets runs carry ``series_id`` for the exact
        # one-running-run database invariant without permitting a mismatched
        # generation and series pair.
        UniqueConstraint("id", "series_id", name="uq_indicator_generation_id_series"),
        CheckConstraint(
            "status IN ('building', 'current', 'superseded', 'failed')",
            name="ck_indicator_generations_status",
        ),
        CheckConstraint("generation > 0", name="ck_indicator_generations_positive_number"),
        Index(
            "uq_indicator_generations_one_current",
            "series_id",
            unique=True,
            postgresql_where=text("status = 'current'"),
            sqlite_where=text("status = 'current'"),
        ),
        Index("ix_indicator_generations_series_status", "series_id", "status"),
        Index("ix_indicator_generations_parent_generation", "parent_generation_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("indicator_series.id"), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_generation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    replacement_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="building")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IndicatorCalculationRun(Base):
    """An immutable calculation attempt for one logical generation."""

    __tablename__ = "indicator_calculation_runs"
    __table_args__ = (
        UniqueConstraint("id", "generation_id", name="uq_indicator_run_id_generation"),
        ForeignKeyConstraint(
            ["generation_id", "series_id"],
            ["indicator_generations.id", "indicator_generations.series_id"],
            name="fk_indicator_run_generation_series",
        ),
        CheckConstraint(
            "run_kind IN ('backfill', 'incremental', 'rebuild')",
            name="ck_indicator_runs_kind",
        ),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_indicator_runs_status",
        ),
        CheckConstraint(
            "range_end IS NULL OR range_start IS NULL OR range_start <= range_end",
            name="ck_indicator_runs_range_order",
        ),
        CheckConstraint("input_count >= 0", name="ck_indicator_runs_input_count"),
        CheckConstraint("result_count >= 0", name="ck_indicator_runs_result_count"),
        CheckConstraint("excluded_count >= 0", name="ck_indicator_runs_excluded_count"),
        CheckConstraint(
            "status <> 'completed' OR "
            "(input_hash IS NOT NULL AND result_hash IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_indicator_runs_completed_evidence",
        ),
        Index(
            "uq_indicator_runs_one_running_per_series",
            "series_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
            sqlite_where=text("status = 'running'"),
        ),
        Index("ix_indicator_runs_generation_status", "generation_id", "status"),
        Index("ix_indicator_runs_series", "series_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    generation_id: Mapped[int] = mapped_column(Integer, nullable=False)
    series_id: Mapped[int] = mapped_column(Integer, nullable=False)
    run_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    input_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    range_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    range_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    excluded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class IndicatorInputSnapshot(Base):
    """Materialized calculator input, readable after source tables change."""

    __tablename__ = "indicator_input_snapshots"
    __table_args__ = (
        UniqueConstraint("calculation_run_id", "generation_id", "trade_date", name="uq_indicator_input_snapshot_run_generation_date"),
        ForeignKeyConstraint(
            ["calculation_run_id", "generation_id"],
            ["indicator_calculation_runs.id", "indicator_calculation_runs.generation_id"],
            name="fk_indicator_input_snapshot_run_generation",
        ),
        ForeignKeyConstraint(
            ["price_observation_identity_snapshot_id", "price_observation_id"],
            [
                "price_observation_identity_snapshots.id",
                "price_observation_identity_snapshots.price_observation_id",
            ],
            name="fk_indicator_input_snapshot_identity_observation",
        ),
        CheckConstraint(f"input_status IN ({_INPUT_STATUS_SQL})", name="ck_indicator_input_snapshots_status"),
        CheckConstraint(
            f"reason_code IS NULL OR reason_code IN ({_REASON_CODE_SQL})",
            name="ck_indicator_input_snapshots_reason",
        ),
        CheckConstraint(
            "price_observation_identity_snapshot_id IS NULL OR price_observation_id IS NOT NULL",
            name="ck_indicator_input_snapshots_identity_requires_observation",
        ),
        CheckConstraint(
            f"mapping_status IS NULL OR mapping_status IN ({_MAPPING_STATUS_SQL})",
            name="ck_indicator_input_snapshots_mapping_status",
        ),
        CheckConstraint(
            "mapping_valid_to IS NULL OR mapping_valid_from IS NULL "
            "OR mapping_valid_from < mapping_valid_to",
            name="ck_indicator_input_snapshots_mapping_range",
        ),
        Index("ix_indicator_input_snapshots_run_date", "calculation_run_id", "trade_date"),
        Index("ix_indicator_input_snapshots_generation", "generation_id"),
        Index("ix_indicator_input_snapshots_instrument", "instrument_id"),
        Index("ix_indicator_input_snapshots_source_symbol", "source_symbol_id"),
        Index("ix_indicator_input_snapshots_observation", "price_observation_id"),
        Index("ix_indicator_input_snapshots_identity_snapshot", "price_observation_identity_snapshot_id"),
        Index("ix_indicator_input_snapshots_provider_mapping", "provider_symbol_mapping_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    calculation_run_id: Mapped[int] = mapped_column(Integer, nullable=False)
    generation_id: Mapped[int] = mapped_column(Integer, nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    source_symbol_id: Mapped[int | None] = mapped_column(ForeignKey("symbols.id"), nullable=True)
    price_observation_id: Mapped[int | None] = mapped_column(
        ForeignKey("price_observations.id"), nullable=True
    )
    price_observation_identity_snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_symbol_mapping_id: Mapped[int | None] = mapped_column(
        ForeignKey("provider_symbols.id"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    adjustment_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    close: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mapping_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    mapping_valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    mapping_valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    resolver_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correction_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    validation_evidence: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    input_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prefix_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class IndicatorValue(Base):
    """Persisted output for an immutable calculation run and explicit definition."""

    __tablename__ = "indicator_values"
    __table_args__ = (
        UniqueConstraint("calculation_run_id", "generation_id", "period", "trade_date", name="uq_indicator_value_run_generation_period_date"),
        ForeignKeyConstraint(
            ["calculation_run_id", "generation_id"],
            ["indicator_calculation_runs.id", "indicator_calculation_runs.generation_id"],
            name="fk_indicator_value_run_generation",
        ),
        CheckConstraint("indicator_kind = 'ema' OR (indicator_kind = 'volume_sma' AND period = 50)", name="ck_indicator_values_definition"),
        CheckConstraint(f"period IN ({_EMA_PERIOD_SQL})", name="ck_indicator_values_period"),
        CheckConstraint(f"status IN ({_EMA_STATUS_SQL})", name="ck_indicator_values_status"),
        CheckConstraint(
            f"reason_code IS NULL OR reason_code IN ({_REASON_CODE_SQL})",
            name="ck_indicator_values_reason",
        ),
        CheckConstraint(
            "(status = 'available' AND value IS NOT NULL AND reason_code IS NULL) "
            "OR (status = 'warming_up' AND reason_code = 'warming_up' AND "
            "((indicator_kind = 'ema' AND value IS NOT NULL) OR "
            "(indicator_kind = 'volume_sma' AND value IS NULL))) "
            "OR (status = 'data_unavailable' AND value IS NULL AND reason_code IS NOT NULL "
            "AND (indicator_kind = 'ema' OR reason_code <> 'warming_up'))",
            name="ck_indicator_values_status_shape",
        ),
        CheckConstraint("available_observations >= 0", name="ck_indicator_values_available_observations"),
        Index("ix_indicator_values_run_period_date", "calculation_run_id", "period", "trade_date"),
        Index("ix_indicator_values_generation", "generation_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    calculation_run_id: Mapped[int] = mapped_column(Integer, nullable=False)
    generation_id: Mapped[int] = mapped_column(Integer, nullable=False)
    indicator_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="ema", server_default="ema")
    period: Mapped[int] = mapped_column(Integer, nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    available_observations: Mapped[int] = mapped_column(Integer, nullable=False)
    input_prefix_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class IndicatorInputPolicy(Base):
    """Immutable, shared OHLCV selection rules.

    PostgreSQL generates SHA-256 over its canonical JSONB row text, excluding
    id/created_at/fingerprint, with timestamps in UTC and sorted parser versions.
    Clients read the generated fingerprint with INSERT RETURNING.
    """

    __tablename__ = "indicator_input_policies"
    __table_args__ = (
        CheckConstraint("version = 'validated-observation-ohlcv-v1'", name="ck_indicator_input_policy_version"),
        UniqueConstraint("fingerprint", name="uq_indicator_input_policy_fingerprint"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(100), nullable=False, default="validated-observation-ohlcv-v1")
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    adjustment_type: Mapped[str] = mapped_column(String(100), nullable=False)
    allowed_parser_versions: Mapped[list[str]] = mapped_column(_JSON_POLICY, nullable=False)
    observation_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    selector_version: Mapped[str] = mapped_column(String(100), nullable=False)
    validation_version: Mapped[str] = mapped_column(String(100), nullable=False)
    correction_version: Mapped[str] = mapped_column(String(100), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, server_default=FetchedValue())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class IndicatorInputEvidence(Base):
    """Reusable immutable OHLCV evidence, including unavailable observations.

    PostgreSQL derives evidence_key from every fact, including nulls, policy and
    validation/correction evidence. Neither run IDs nor creation time enter it.
    """

    __tablename__ = "indicator_input_evidence"
    __table_args__ = (
        UniqueConstraint("evidence_key", name="uq_indicator_input_evidence_key"),
        ForeignKeyConstraint(
            ["price_observation_identity_snapshot_id", "price_observation_id"],
            ["price_observation_identity_snapshots.id", "price_observation_identity_snapshots.price_observation_id"],
            name="fk_indicator_evidence_identity_observation",
        ),
        CheckConstraint(f"input_status IN ({_INPUT_STATUS_SQL})", name="ck_indicator_evidence_status"),
        CheckConstraint(f"reason_code IS NULL OR reason_code IN ({_REASON_CODE_SQL})", name="ck_indicator_evidence_reason"),
        CheckConstraint("price_observation_identity_snapshot_id IS NULL OR price_observation_id IS NOT NULL", name="ck_indicator_evidence_identity_observation"),
        CheckConstraint(f"mapping_status IS NULL OR mapping_status IN ({_MAPPING_STATUS_SQL})", name="ck_indicator_evidence_mapping_status"),
        CheckConstraint("mapping_valid_to IS NULL OR mapping_valid_from IS NULL OR mapping_valid_from < mapping_valid_to", name="ck_indicator_evidence_mapping_range"),
        Index("ix_indicator_evidence_policy_instrument_date", "input_policy_id", "instrument_id", "trade_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    input_policy_id: Mapped[int] = mapped_column(ForeignKey("indicator_input_policies.id"), nullable=False)
    evidence_key: Mapped[str] = mapped_column(String(64), nullable=False, server_default=FetchedValue())
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), nullable=False)
    source_symbol_id: Mapped[int | None] = mapped_column(ForeignKey("symbols.id"), nullable=True)
    price_observation_id: Mapped[int | None] = mapped_column(
        ForeignKey("price_observations.id"), nullable=True
    )
    price_observation_identity_snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_symbol_mapping_id: Mapped[int | None] = mapped_column(
        ForeignKey("provider_symbols.id"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    adjustment_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    close: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mapping_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    mapping_valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    mapping_valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    resolver_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correction_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    validation_evidence: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    input_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class IndicatorRunInput(Base):
    """Ordered evidence references; PostgreSQL enforces the run's policy/identity."""

    __tablename__ = "indicator_run_inputs"
    __table_args__ = (
        UniqueConstraint("calculation_run_id", "ordinal", name="uq_indicator_run_input_ordinal"),
        UniqueConstraint("calculation_run_id", "evidence_id", name="uq_indicator_run_input_evidence"),
        CheckConstraint("ordinal >= 0", name="ck_indicator_run_input_ordinal"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    calculation_run_id: Mapped[int] = mapped_column(ForeignKey("indicator_calculation_runs.id"), nullable=False)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("indicator_input_evidence.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    prefix_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
