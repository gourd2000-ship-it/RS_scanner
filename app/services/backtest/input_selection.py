"""Choose and freeze only complete historical inputs for a backtest attempt."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from collections.abc import Iterable, Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.backtest_dataset import (
    BacktestDataset,
    BacktestDatasetIndicatorSnapshot,
    BacktestDatasetIndicatorSnapshotRow,
    BacktestDatasetIndicatorSnapshotSource,
    BacktestDatasetMembership,
    BacktestDatasetPrice,
    BacktestDatasetRs,
    BacktestDatasetRsRun,
)
from app.models.benchmark import Benchmark
from app.models.benchmark_daily_price import BenchmarkDailyPrice
from app.models.indicator import (
    IndicatorCalculationRun,
    IndicatorGeneration,
    IndicatorInputPolicy,
    IndicatorSeries,
)
from app.repositories.backtest_repository import BenchmarkSnapshotInput
from app.core.market_calendar import krx_market_day_status
from app.services.backtest.schedule import rebalance_dates_for_trading_days


@dataclass(frozen=True)
class InputUnavailableReason:
    code: str
    detail: str
    instrument_id: int | None = None
    trade_date: date | None = None
    field: str | None = None
    indicator_kind: str | None = None
    original_status: str | None = None
    original_reason_code: str | None = None


class BacktestInputUnavailable(ValueError):
    def __init__(
        self,
        reasons: list[InputUnavailableReason],
        *,
        dataset: BacktestDataset | None = None,
        rs_run: BacktestDatasetRsRun | None = None,
    ) -> None:
        self.reasons = tuple(reasons)
        self.dataset = dataset
        self.rs_run = rs_run
        super().__init__("backtest input is unavailable")


@dataclass(frozen=True)
class SelectedBacktestInputs:
    dataset: BacktestDataset
    dataset_manifest_hash: str
    rs_run: BacktestDatasetRsRun
    benchmark_snapshots: tuple[BenchmarkSnapshotInput, BenchmarkSnapshotInput]
    lookback_excluded_candidates: frozenset[tuple[int, str, date]]
    indicator_snapshots: Mapping[str, BacktestDatasetIndicatorSnapshot]


def _snapshot_hash(market: str, code: str, rows: list[BenchmarkDailyPrice]) -> str:
    material = [[market, code, item.trade_date.isoformat(), format(item.close, "f")] for item in rows]
    return sha256(json.dumps(material, separators=(",", ":")).encode()).hexdigest()


def _latest_dataset(session: Session, *, range_start: date, range_end: date, markets: set[str]) -> BacktestDataset | None:
    candidates = list(session.scalars(
        select(BacktestDataset).where(
            BacktestDataset.status == "active", BacktestDataset.range_start <= range_start,
            BacktestDataset.range_end >= range_end,
        ).order_by(BacktestDataset.created_at.desc(), BacktestDataset.id.desc())
    ))
    for dataset in candidates:
        if (
            isinstance(dataset.manifest, dict)
            and dataset.manifest.get("publication_scope") == "complete_segments_only"
            and dataset.final_manifest_hash
            and sha256(json.dumps(dataset.manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest() == dataset.final_manifest_hash
            and markets <= set(dataset.markets or [])
        ):
            return dataset
    return None


def _expected_krx_days(range_start: date, range_end: date, *, configured_closed_dates: str) -> set[date]:
    days: set[date] = set()
    current = range_start
    while current <= range_end:
        if krx_market_day_status(current, configured_closed_dates=configured_closed_dates).is_open:
            days.add(current)
        current += timedelta(days=1)
    return days


def select_backtest_inputs(
    session: Session, *, range_start: date, range_end: date, markets: list[str],
    rebalance_dates: list[date] | None = None, return_lookback_days: int = 0,
    market_closed_dates: str = "",
    indicator_fields_by_side: Mapping[str, Iterable[str]] | None = None,
    rebalance_interval_days: int | None = None,
) -> SelectedBacktestInputs:
    """Validate inputs and return immutable copies suitable for ``enqueue_run``.

    Listing starts and missing preparation history are intentionally not errors:
    those instruments simply never enter the candidate set before sufficient
    history exists.  A row that *is* a selected membership on a required day
    must, however, have complete OHLCV and RS input.
    """
    requested_markets = set(markets)
    if not requested_markets or not requested_markets <= {"KOSPI", "KOSDAQ"} or range_start > range_end:
        raise ValueError("invalid backtest range or market")
    if return_lookback_days < 0:
        raise ValueError("return lookback days cannot be negative")
    reasons: list[InputUnavailableReason] = []
    dataset = _latest_dataset(session, range_start=range_start, range_end=range_end, markets=requested_markets)
    if dataset is None:
        raise BacktestInputUnavailable([InputUnavailableReason("dataset_missing", "no active complete dataset covers the requested range")])
    rs_run = session.scalar(select(BacktestDatasetRsRun).where(
        BacktestDatasetRsRun.backtest_dataset_id == dataset.id,
        BacktestDatasetRsRun.status == "completed",
    ).order_by(BacktestDatasetRsRun.created_at.desc(), BacktestDatasetRsRun.id.desc()))
    if rs_run is None:
        reasons.append(InputUnavailableReason("rs_run_missing", "no completed RS result exists for the selected dataset"))

    snapshots: list[BenchmarkSnapshotInput] = []
    expected_benchmark_dates = _expected_krx_days(
        range_start, range_end, configured_closed_dates=market_closed_dates
    )
    if range_start not in expected_benchmark_dates or range_end not in expected_benchmark_dates:
        reasons.append(InputUnavailableReason("benchmark_boundary_not_trading_day", "start and end must be Korean trading days"))
    for market in ("KOSPI", "KOSDAQ"):
        benchmark = session.scalar(select(Benchmark).where(Benchmark.benchmark_code == market))
        if benchmark is None:
            reasons.append(InputUnavailableReason("benchmark_missing", f"{market} benchmark is missing", field=market))
            continue
        rows = list(session.scalars(select(BenchmarkDailyPrice).where(
            BenchmarkDailyPrice.benchmark_id == benchmark.id,
            BenchmarkDailyPrice.trade_date >= range_start,
            BenchmarkDailyPrice.trade_date <= range_end,
        ).order_by(BenchmarkDailyPrice.trade_date)))
        dates = {row.trade_date for row in rows}
        if range_start not in dates or range_end not in dates:
            reasons.append(InputUnavailableReason("benchmark_boundary_missing", f"{market} lacks the requested start or end trading day", field=market))
        for missing_date in sorted(expected_benchmark_dates - dates):
            reasons.append(InputUnavailableReason("benchmark_price_missing", f"{market} benchmark close is missing", trade_date=missing_date, field="close"))
        if not rows:
            reasons.append(InputUnavailableReason("benchmark_price_missing", f"{market} benchmark close series is missing", field="close"))
        else:
            snapshots.append(BenchmarkSnapshotInput(market, benchmark.benchmark_code, _snapshot_hash(market, benchmark.benchmark_code, rows), tuple((r.trade_date, Decimal(r.close)) for r in rows)))
    memberships = list(session.scalars(select(BacktestDatasetMembership).where(
        BacktestDatasetMembership.backtest_dataset_id == dataset.id,
        BacktestDatasetMembership.market.in_(requested_markets),
        BacktestDatasetMembership.trade_date >= range_start,
        BacktestDatasetMembership.trade_date <= range_end,
    )))
    price_keys = {(item.instrument_id, item.market, item.trade_date) for item in session.scalars(select(BacktestDatasetPrice).where(
        BacktestDatasetPrice.backtest_dataset_id == dataset.id,
        BacktestDatasetPrice.market.in_(requested_markets),
        BacktestDatasetPrice.trade_date >= range_start,
        BacktestDatasetPrice.trade_date <= range_end,
    ))}
    indicator_rebalance_dates = (
        set(rebalance_dates_for_trading_days((key[2] for key in price_keys), rebalance_interval_days))
        if rebalance_interval_days is not None
        else set(rebalance_dates or [])
    )
    indicator_snapshots, indicator_reasons = _select_indicator_snapshots(
        session,
        dataset=dataset,
        price_keys=price_keys,
        markets=requested_markets,
        range_start=range_start,
        range_end=range_end,
        rebalance_dates=indicator_rebalance_dates,
        market_closed_dates=market_closed_dates,
        indicator_fields_by_side=indicator_fields_by_side or {},
    )
    reasons.extend(indicator_reasons)
    signal_dates = set(rebalance_dates or [])
    lookback_excluded: set[tuple[int, str, date]] = set()
    rs_keys = set()
    if rs_run is not None and signal_dates:
        rs_keys = {(item.instrument_id, item.market, item.trade_date) for item in session.scalars(select(BacktestDatasetRs).where(
            BacktestDatasetRs.backtest_dataset_rs_run_id == rs_run.id,
            BacktestDatasetRs.trade_date.in_(signal_dates), BacktestDatasetRs.status == "available",
        ))}
    for member in memberships:
        # Inactive/not-yet-tradable rows are never a candidate; a valid listing
        # begins only when its membership says it is an expected trade row.
        if member.price_expectation != "expected" or member.trading_status not in {"trading", "normal"}:
            continue
        key = (member.instrument_id, member.market, member.trade_date)
        if key not in price_keys:
            reasons.append(InputUnavailableReason("ohlcv_missing", "required complete OHLCV row is absent", member.instrument_id, member.trade_date, "ohlcv"))
        if member.trade_date in signal_dates:
            historical_price_count = session.scalar(select(BacktestDatasetPrice.id).where(
                BacktestDatasetPrice.backtest_dataset_id == dataset.id,
                BacktestDatasetPrice.instrument_id == member.instrument_id,
                BacktestDatasetPrice.market == member.market,
                BacktestDatasetPrice.trade_date <= member.trade_date,
            ).order_by(BacktestDatasetPrice.trade_date).offset(return_lookback_days).limit(1))
            # A listing that has not accumulated the requested N prior closes
            # is not an unavailable dataset: it is simply ineligible on this
            # signal date and can become eligible later.
            if historical_price_count is None:
                lookback_excluded.add(key)
                continue
            if key not in rs_keys:
                reasons.append(InputUnavailableReason("rs_value_missing", "required rebalance-day RS value is absent", member.instrument_id, member.trade_date, "rs"))
    if reasons:
        raise BacktestInputUnavailable(reasons, dataset=dataset, rs_run=rs_run)
    if len(snapshots) != 2:
        raise BacktestInputUnavailable([InputUnavailableReason("benchmark_missing", "both benchmarks are required")])
    return SelectedBacktestInputs(
        dataset, dataset.final_manifest_hash, rs_run, tuple(snapshots), frozenset(lookback_excluded),
        indicator_snapshots,
    )


_INDICATOR_DEFINITIONS = {
    "volume_sma50": ("volume_sma", 50, "volume-sma-v1"),
    "atr14": ("atr", 14, "wilder-atr-14-v1"),
}


def _select_indicator_snapshots(
    session: Session,
    *,
    dataset: BacktestDataset,
    price_keys: set[tuple[int, str, date]],
    markets: set[str],
    range_start: date,
    range_end: date,
    rebalance_dates: set[date],
    market_closed_dates: str,
    indicator_fields_by_side: Mapping[str, Iterable[str]],
) -> tuple[dict[str, BacktestDatasetIndicatorSnapshot], list[InputUnavailableReason]]:
    buy_fields = set(indicator_fields_by_side.get("buy", ())) & set(_INDICATOR_DEFINITIONS)
    sell_fields = set(indicator_fields_by_side.get("sell", ())) & set(_INDICATOR_DEFINITIONS)
    required_fields = buy_fields | sell_fields
    if not required_fields:
        return {}, []

    sell_dates = _expected_krx_days(
        range_start, range_end, configured_closed_dates=market_closed_dates
    )
    required_keys: dict[str, set[tuple[int, date]]] = {field: set() for field in required_fields}
    for instrument_id, market, trade_date in price_keys:
        if market not in markets:
            continue
        key = (instrument_id, trade_date)
        if trade_date in rebalance_dates:
            for field in buy_fields:
                required_keys[field].add(key)
        if trade_date in sell_dates:
            for field in sell_fields:
                required_keys[field].add(key)

    selected: dict[str, BacktestDatasetIndicatorSnapshot] = {}
    reasons: list[InputUnavailableReason] = []
    for field in sorted(required_fields):
        indicator_kind, period, formula_version = _INDICATOR_DEFINITIONS[field]
        candidates = list(session.scalars(
            select(BacktestDatasetIndicatorSnapshot)
            .where(
                BacktestDatasetIndicatorSnapshot.backtest_dataset_id == dataset.id,
                BacktestDatasetIndicatorSnapshot.indicator_kind == indicator_kind,
                BacktestDatasetIndicatorSnapshot.status == "complete",
            )
            .order_by(
                BacktestDatasetIndicatorSnapshot.completed_at.desc(),
                BacktestDatasetIndicatorSnapshot.id.desc(),
            )
        ))
        if not candidates:
            reasons.append(InputUnavailableReason(
                "indicator_snapshot_missing", "no complete indicator snapshot is pinned to the selected dataset",
                field=field, indicator_kind=indicator_kind,
            ))
            continue

        # A rebuilt indicator bundle is a new immutable version. Pick the latest
        # completed bundle deterministically and pin its exact id and hash below.
        snapshot = candidates[0]
        if not _snapshot_matches_dataset(
            session, snapshot=snapshot, dataset=dataset, indicator_kind=indicator_kind,
            period=period, formula_version=formula_version,
        ):
            reasons.append(InputUnavailableReason(
                "indicator_evidence_mismatch", "indicator snapshot metadata or source lineage does not match the selected dataset",
                field=field, indicator_kind=indicator_kind,
            ))
            continue

        selected[field] = snapshot
        coverage_matches = _snapshot_covers_dataset(session, snapshot=snapshot, dataset=dataset)
        requested_keys = required_keys[field]
        if not requested_keys:
            if not coverage_matches:
                reasons.append(InputUnavailableReason(
                    "indicator_evidence_mismatch", "indicator snapshot does not cover the finalized dataset rows",
                    field=field, indicator_kind=indicator_kind,
                ))
            continue
        instrument_ids = {instrument_id for instrument_id, _ in requested_keys}
        trade_dates = {trade_date for _, trade_date in requested_keys}
        rows = list(session.scalars(
            select(BacktestDatasetIndicatorSnapshotRow).where(
                BacktestDatasetIndicatorSnapshotRow.snapshot_id == snapshot.id,
                BacktestDatasetIndicatorSnapshotRow.instrument_id.in_(instrument_ids),
                BacktestDatasetIndicatorSnapshotRow.trade_date.in_(trade_dates),
            )
        ))
        row_by_key = {(row.instrument_id, row.trade_date): row for row in rows}
        source_rows = list(session.scalars(
            select(BacktestDatasetIndicatorSnapshotSource).where(
                BacktestDatasetIndicatorSnapshotSource.snapshot_id == snapshot.id,
            )
        ))
        source_by_instrument = {row.instrument_id: row for row in source_rows}
        for instrument_id, trade_date in sorted(requested_keys, key=lambda item: (item[1], item[0])):
            row = row_by_key.get((instrument_id, trade_date))
            if row is None:
                reasons.append(InputUnavailableReason(
                    "indicator_value_missing", "required indicator row is missing from the pinned snapshot",
                    instrument_id=instrument_id, trade_date=trade_date, field=field,
                    indicator_kind=indicator_kind,
                ))
                continue
            source = source_by_instrument.get(instrument_id)
            if not _snapshot_row_matches_source(row, source=source, snapshot=snapshot):
                reasons.append(InputUnavailableReason(
                    "indicator_evidence_mismatch", "indicator row source or value evidence does not match the pinned snapshot",
                    instrument_id=instrument_id, trade_date=trade_date, field=field,
                    indicator_kind=indicator_kind, original_status=row.status,
                    original_reason_code=row.reason_code,
                ))
                continue
            if row.status != "available":
                reasons.append(InputUnavailableReason(
                    "indicator_value_unavailable", "required indicator row is not available",
                    instrument_id=instrument_id, trade_date=trade_date, field=field,
                    indicator_kind=indicator_kind, original_status=row.status,
                    original_reason_code=row.reason_code,
                ))
        if not coverage_matches:
            reasons.append(InputUnavailableReason(
                "indicator_evidence_mismatch", "indicator snapshot does not cover the finalized dataset rows",
                field=field, indicator_kind=indicator_kind,
            ))
    return selected, reasons


def _snapshot_matches_dataset(
    session: Session,
    *,
    snapshot: BacktestDatasetIndicatorSnapshot,
    dataset: BacktestDataset,
    indicator_kind: str,
    period: int,
    formula_version: str,
) -> bool:
    source_lineage = list(session.execute(
        select(
            BacktestDatasetIndicatorSnapshotSource,
            IndicatorSeries,
            IndicatorInputPolicy,
            IndicatorCalculationRun,
            IndicatorGeneration,
        )
        .join(IndicatorSeries, IndicatorSeries.id == BacktestDatasetIndicatorSnapshotSource.indicator_series_id)
        .join(IndicatorInputPolicy, IndicatorInputPolicy.id == BacktestDatasetIndicatorSnapshotSource.input_policy_id)
        .join(IndicatorCalculationRun, IndicatorCalculationRun.id == BacktestDatasetIndicatorSnapshotSource.calculation_run_id)
        .join(IndicatorGeneration, IndicatorGeneration.id == BacktestDatasetIndicatorSnapshotSource.generation_id)
        .where(BacktestDatasetIndicatorSnapshotSource.snapshot_id == snapshot.id)
    ))
    sources = [item[0] for item in source_lineage]
    source_instrument_ids = {source.instrument_id for source in sources}
    dataset_instrument_ids = set(session.scalars(
        select(BacktestDatasetPrice.instrument_id)
        .where(BacktestDatasetPrice.backtest_dataset_id == dataset.id)
        .distinct()
    ))
    fingerprints = {source.source_policy_fingerprint for source in sources}
    adjustment_provider, separator, adjustment_type = (dataset.adjustment_policy or "").partition(":")
    lineage_matches = bool(separator and adjustment_provider and adjustment_type) and all(
        source.instrument_id == series.instrument_id
        and series.indicator_kind == indicator_kind
        and series.input_policy_version == "validated-observation-ohlcv-v1"
        and series.formula_version == formula_version
        and series.source_provider == adjustment_provider
        and series.adjustment_policy == adjustment_type
        and series.input_policy_id == policy.id
        and series.input_field == ("volume" if indicator_kind == "volume_sma" else "high-low-close")
        and series.periods == str(period)
        and policy.version == "validated-observation-ohlcv-v1"
        and policy.provider == adjustment_provider
        and policy.adjustment_type == adjustment_type
        and policy.fingerprint == source.source_policy_fingerprint == snapshot.source_policy_fingerprint
        and run.status == "completed"
        and run.series_id == series.id
        and run.generation_id == generation.id
        and generation.series_id == series.id
        and generation.status in {"current", "superseded"}
        and run.input_hash == source.input_hash
        and run.result_hash == source.result_hash
        for source, series, policy, run, generation in source_lineage
    )
    return (
        snapshot.backtest_dataset_id == dataset.id
        and snapshot.dataset_id == dataset.dataset_id
        and snapshot.dataset_manifest_hash == dataset.final_manifest_hash
        and snapshot.range_start == dataset.range_start
        and snapshot.range_end == dataset.range_end
        and snapshot.indicator_kind == indicator_kind
        and snapshot.period == period
        and snapshot.formula_version == formula_version
        and snapshot.status == "complete"
        and _is_hash(snapshot.source_policy_fingerprint)
        and _is_hash(snapshot.input_hash)
        and _is_hash(snapshot.result_hash)
        and _is_hash(snapshot.content_hash)
        and snapshot.source_count == len(sources) > 0
        and source_instrument_ids == dataset_instrument_ids
        and fingerprints == {snapshot.source_policy_fingerprint}
        and lineage_matches
        and all(
            _is_hash(source.input_hash) and _is_hash(source.result_hash)
            and _is_hash(source.source_policy_fingerprint)
            for source in sources
        )
    )


def _snapshot_covers_dataset(
    session: Session,
    *,
    snapshot: BacktestDatasetIndicatorSnapshot,
    dataset: BacktestDataset,
) -> bool:
    actual_row_count = session.scalar(select(func.count(BacktestDatasetIndicatorSnapshotRow.id)).where(
        BacktestDatasetIndicatorSnapshotRow.snapshot_id == snapshot.id,
    )) or 0
    expected_row_count = session.scalar(select(func.count(BacktestDatasetPrice.id)).where(
        BacktestDatasetPrice.backtest_dataset_id == dataset.id,
    )) or 0
    return snapshot.row_count == actual_row_count == expected_row_count


def _snapshot_row_matches_source(
    row: BacktestDatasetIndicatorSnapshotRow,
    *,
    source: BacktestDatasetIndicatorSnapshotSource | None,
    snapshot: BacktestDatasetIndicatorSnapshot,
) -> bool:
    if source is None or row.source_id != source.id:
        return False
    if (
        row.snapshot_id != snapshot.id
        or row.instrument_id != source.instrument_id
        or row.status not in {"available", "warming_up", "data_unavailable"}
        or row.available_observations < 0
        or not _is_hash(row.input_prefix_hash)
        or not _is_hash(row.source_evidence_key)
        or not _is_hash(row.row_hash)
        or row.mapping_status != "matched"
        or row.source_value_id <= 0
        or row.source_run_input_id <= 0
        or row.source_evidence_id <= 0
    ):
        return False
    if row.status == "available":
        return row.value is not None and row.value.is_finite() and row.value >= 0 and row.reason_code is None
    if row.status == "warming_up":
        return row.value is None and row.reason_code == "warming_up"
    return row.value is None and bool(row.reason_code) and row.reason_code != "warming_up"


def _is_hash(value: str | None) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True
