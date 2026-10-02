"""Choose and freeze only complete historical inputs for a backtest attempt."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.backtest_dataset import BacktestDataset, BacktestDatasetMembership, BacktestDatasetPrice, BacktestDatasetRs, BacktestDatasetRsRun
from app.models.benchmark import Benchmark
from app.models.benchmark_daily_price import BenchmarkDailyPrice
from app.repositories.backtest_repository import BenchmarkSnapshotInput
from app.core.market_calendar import krx_market_day_status


@dataclass(frozen=True)
class InputUnavailableReason:
    code: str
    detail: str
    instrument_id: int | None = None
    trade_date: date | None = None
    field: str | None = None


class BacktestInputUnavailable(ValueError):
    def __init__(self, reasons: list[InputUnavailableReason]) -> None:
        self.reasons = tuple(reasons)
        super().__init__("backtest input is unavailable")


@dataclass(frozen=True)
class SelectedBacktestInputs:
    dataset: BacktestDataset
    dataset_manifest_hash: str
    rs_run: BacktestDatasetRsRun
    benchmark_snapshots: tuple[BenchmarkSnapshotInput, BenchmarkSnapshotInput]
    lookback_excluded_candidates: frozenset[tuple[int, str, date]]


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
        raise BacktestInputUnavailable(reasons)
    if len(snapshots) != 2:
        raise BacktestInputUnavailable([InputUnavailableReason("benchmark_missing", "both benchmarks are required")])
    return SelectedBacktestInputs(
        dataset, dataset.final_manifest_hash, rs_run, tuple(snapshots), frozenset(lookback_excluded)
    )
